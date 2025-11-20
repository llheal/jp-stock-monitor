import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股实盘全景", page_icon="📱", layout="centered")

# --- 1. 智能默认值 ---
FALLBACK_CODES = "7203, 9984, 8035" 

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 持仓配置")
user_input = st.sidebar.text_area("持仓代码 (逗号分隔)", value=initial_value, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心函数 ---

def get_safe_price(hist_data):
    """安全获取收盘价"""
    if not hist_data.empty:
        return hist_data['Close'].iloc[-1]
    return 0.0

def fetch_market_data(ticker_symbol, start_str, is_index=False):
    """获取全方位数据"""
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # 1. 获取数据
        hist_recent = stock.history(period="5d")
        hist_mtd = stock.history(start=start_str)
        if hist_mtd.empty:
             hist_mtd = stock.history(period="1mo")

        # 2. 确定现价 (优先盘中实时)
        try:
            intraday = stock.history(period="1d", interval="5m")
            if not intraday.empty:
                current_price = intraday['Close'].iloc[-1]
            else:
                current_price = get_safe_price(hist_recent)
        except:
            current_price = get_safe_price(hist_recent)

        # 3. 日收益 (Daily)
        daily_ret = 0.0
        if len(hist_recent) >= 2:
            prev_close = hist_recent['Close'].iloc[-2]
            if prev_close > 0:
                daily_ret = (current_price - prev_close) / prev_close

        # 4. 月收益 (MTD)
        mtd_ret = 0.0
        buy_price = 0.0
        buy_date = "N/A"
        
        if not hist_mtd.empty:
            buy_price = hist_mtd.iloc[0]['Open']
            buy_date = hist_mtd.index[0].strftime('%m-%d')
            if buy_price > 0:
                mtd_ret = (current_price - buy_price) / buy_price

        # 5. 获取名称
        name = ticker_symbol
        if not is_index:
            try:
                info = stock.info
                name = info.get('longName', info.get('shortName', ticker_symbol))
            except:
                pass

        return {
            "name": name,
            "price": current_price,
            "daily_ret": daily_ret,
            "mtd_ret": mtd_ret,
            "buy_price": buy_price,
            "buy_date": buy_date,
            "valid": True
        }
    except:
        return {"valid": False}

def fetch_portfolio_data(codes, start_str):
    data_list = []
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        ticker = f"{code}.T" if not code.endswith(".T") else code
        
        data = fetch_market_data(ticker, start_str)
        if data["valid"]:
            data_list.append({
                "代码": code,
                "名称": data["name"],
                "现价": data["price"],
                "买入价": data["buy_price"],
                "日收益": data["daily_ret"],
                "月收益": data["mtd_ret"]
            })
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主程序 ---

jp_tz = pytz.timezone('Asia/Tokyo')
now = datetime.now(jp_tz)
start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
start_str = start_of_month.strftime('%Y-%m-%d')

st.title("📱 日股实盘全景")

clean_codes = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_str = ",".join(clean_codes)

if st.button("🔄 刷新详细行情", type="primary", use_container_width=True):
    st.query_params["codes"] = clean_str
    
    # 1. 获取指数
    n225 = fetch_market_data("^N225", start_str, is_index=True)
    topx = fetch_market_data("^TOPX", start_str, is_index=True)
    etf  = fetch_market_data("1306.T", start_str, is_index=True)
    
    # 2. 获取持仓
    df = fetch_portfolio_data(clean_codes, start_str)
    
    # --- A. 指数面板 ---
    st.caption(f"📊 市场基准 ({now.strftime('%H:%M')})")
    
    c1, c2, c3 = st.columns(3)
    
    # 辅助函数：生成带颜色的标签
    def show_idx_metric(label, data):
        if data["valid"]:
            # 注意：Streamlit中 delta_color="inverse" 代表 红涨绿跌
            st.metric(
                label=f"{label} (月 {data['mtd_ret']:+.1%})",
                value=f"{data['price']:,.0f}",
                delta=f"{data['daily_ret']:+.2%} 日",
                delta_color="inverse" 
            )
        else:
            st.metric(label, "N/A")

    with c1: show_idx_metric("日经225", n225)
    with c2:
        # TOPIX指数有时候获取不到，做个特判
        if topx["valid"] and topx["price"] > 0:
            st.metric(
                label=f"TOPIX (月 {topx['mtd_ret']:+.1%})",
                value=f"{topx['price']:,.2f}",
                delta=f"{topx['daily_ret']:+.2%} 日",
                delta_color="inverse"
            )
        else:
            st.metric("TOPIX", "无数据")
    with c3: show_idx_metric("ETF 1306", etf)

    st.markdown("---")

    # --- B. 策略表现 ---
    if not df.empty:
        avg_ret = df['月收益'].mean()
        total_ret = avg_ret * leverage
        
        # Alpha 优先用 ETF 对比
        bench_ret = etf['mtd_ret'] if etf['valid'] else 0
        alpha = total_ret - bench_ret
        
        st.caption("📈 组合表现 (本月累计)")
        sc1, sc2 = st.columns(2)
        with sc1:
             st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", 
                      delta_color="inverse") # 强制红涨绿跌
        with sc2:
             # Alpha 只显示数值
             st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}", delta_color="off")
             
        st.divider()

        # --- C. 持仓列表 ---
        st.subheader(f"持仓详情 ({len(df)}只)")
        df = df.sort_values(by='月收益', ascending=False)
        
        for _, row in df.iterrows():
            name = row['名称']
            code = row['代码']
            price = row['现价']
            cost = row['买入价']
            d_ret = row['日收益']
            m_ret = row['月收益']
            
            # 这里的颜色是给 markdown 用的字符串
            # 红涨绿跌
            c_day = "red" if d_ret > 0 else "green"
            c_mon = "red" if m_ret > 0 else "green"
            
            with st.container():
                # 第一行：名称
                st.markdown(f"**{code} | {name}**")
                
                # 第二行：数据
                col1, col2, col3 = st.columns([1.2, 1, 1])
                
                with col1:
                    st.write(f"¥{price:,.0f}")
                    st.caption(f"本:¥{cost:,.0f}")
                
                with col2:
                    st.markdown(f":{c_day}[{d_ret:+.2%}]")
                    st.caption("今日")
                    
                with col3:
                    st.markdown(f":{c_mon}[**{m_ret:+.2%}**]")
                    st.caption("本月")
                
                st.divider()
    else:
        st.error("无法获取数据")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 列表已保存，请收藏当前网址。")
