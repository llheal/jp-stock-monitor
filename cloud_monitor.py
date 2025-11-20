import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股全景监控", page_icon="📱", layout="centered")

# --- 1. 智能默认值逻辑 ---
FALLBACK_CODES = "7203, 9984, 8035" 

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏配置 ---
st.sidebar.header("⚙️ 持仓配置")
user_input = st.sidebar.text_area("持仓代码 (逗号分隔)", value=initial_value, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心数据获取函数 ---

def get_safe_price(hist_data):
    """从历史数据中安全获取最新价格"""
    if not hist_data.empty:
        return hist_data['Close'].iloc[-1]
    return 0.0

def fetch_market_data(ticker_symbol, start_str, is_index=False):
    """
    获取标的的全方位数据：
    名称, 现价, 昨收, 月初开盘, 日收益, 月收益
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # 1. 获取最近5天数据 (用于计算现价和日收益)
        hist_recent = stock.history(period="5d")
        
        # 2. 获取本月数据 (用于计算月收益)
        hist_mtd = stock.history(start=start_str)
        if hist_mtd.empty:
             hist_mtd = stock.history(period="1mo")

        # 3. 确定现价
        # 尝试获取盘中 5m 数据 (最实时)
        try:
            intraday = stock.history(period="1d", interval="5m")
            if not intraday.empty:
                current_price = intraday['Close'].iloc[-1]
            else:
                current_price = get_safe_price(hist_recent)
        except:
            current_price = get_safe_price(hist_recent)

        # 4. 计算日收益 (Daily Return)
        daily_ret = 0.0
        if len(hist_recent) >= 2:
            # 昨收 = 倒数第二行
            prev_close = hist_recent['Close'].iloc[-2]
            if prev_close > 0:
                daily_ret = (current_price - prev_close) / prev_close

        # 5. 计算月收益 (MTD Return)
        mtd_ret = 0.0
        buy_price = 0.0
        buy_date = "N/A"
        
        if not hist_mtd.empty:
            buy_price = hist_mtd.iloc[0]['Open']
            buy_date = hist_mtd.index[0].strftime('%m-%d')
            if buy_price > 0:
                mtd_ret = (current_price - buy_price) / buy_price

        # 6. 获取名称 (仅针对个股，指数通常不需要)
        name = ticker_symbol
        if not is_index:
            try:
                # yfinance 的 info 可能会慢，如果超时会跳过
                info = stock.info
                # 优先取长名，取不到取短名，再取不到取代码
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
    except Exception as e:
        return {"valid": False}

def fetch_portfolio_data(codes, start_str):
    data_list = []
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        
        ticker_symbol = f"{code}.T" if not code.endswith(".T") else code
        
        data = fetch_market_data(ticker_symbol, start_str)
        
        if data["valid"]:
            data_list.append({
                "代码": code,
                "名称": data["name"],
                "现价": data["price"],
                "买入价": data["buy_price"],
                "买入日": data["buy_date"],
                "日收益": data["daily_ret"],
                "月收益": data["mtd_ret"]
            })
        
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主程序逻辑 ---

jp_tz = pytz.timezone('Asia/Tokyo')
now = datetime.now(jp_tz)
start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
start_str = start_of_month.strftime('%Y-%m-%d')

st.title("📱 日股实盘全景")

# 处理列表
clean_codes_list = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_codes_str = ",".join(clean_codes_list)

if st.button("🔄 刷新详细行情", type="primary", use_container_width=True):
    st.query_params["codes"] = clean_codes_str
    
    # 1. 获取三大指数
    # 注意: ^TOPX 数据可能不稳定，如果显示 0 或 N/A 请参考 1306.T
    n225_data = fetch_market_data("^N225", start_str, is_index=True)
    topx_data = fetch_market_data("^TOPX", start_str, is_index=True) # 官方指数
    etf_data  = fetch_market_data("1306.T", start_str, is_index=True) # ETF
    
    # 2. 获取持仓
    df = fetch_portfolio_data(clean_codes_list, start_str)
    
    # --- 显示：指数概况 (3列布局) ---
    st.caption(f"📊 市场基准 ({now.strftime('%H:%M')})")
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        if n225_data["valid"]:
            st.metric("日经225", f"{n225_data['price']:,.0f}", f"{n225_data['daily_ret']:+.2%} 日")
        else:
            st.metric("日经225", "N/A")
            
    with c2:
        if topx_data["valid"] and topx_data["price"] > 0:
            st.metric("TOPIX指数", f"{topx_data['price']:,.2f}", f"{topx_data['daily_ret']:+.2%} 日")
        else:
            st.metric("TOPIX指数", "无数据", help="Yahoo数据源暂无纯指数数据")

    with c3:
        if etf_data["valid"]:
            st.metric("TOPIX ETF", f"{etf_data['price']:,.0f}", f"{etf_data['daily_ret']:+.2%} 日")
        else:
            st.metric("ETF 1306", "N/A")

    st.markdown("---")

    # --- 显示：策略表现 ---
    if not df.empty:
        avg_ret = df['月收益'].mean()
        total_ret = avg_ret * leverage
        
        # Alpha 计算 (优先用 ETF，如果 ETF 也没有就用 0)
        benchmark_ret = etf_data['mtd_ret'] if etf_data['valid'] else 0
        alpha = total_ret - benchmark_ret
        
        st.caption("📈 组合表现 (本月累计)")
        sc1, sc2 = st.columns(2)
        with sc1:
             st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", 
                      delta_color="normal" if total_ret > 0 else "inverse")
        with sc2:
             st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}", delta_color="off")
             
        st.divider()

        # --- 显示：个股详情 (增强版列表) ---
        st.subheader(f"持仓详情 ({len(df)}只)")
        
        # 按月收益排序
        df = df.sort_values(by='月收益', ascending=False)
        
        for _, row in df.iterrows():
            # 准备数据
            name = row['名称']
            code = row['代码']
            price = row['现价']
            cost = row['买入价']
            day_ret = row['日收益']
            mon_ret = row['月收益']
            
            # 颜色定义
            color_mon = "red" if mon_ret > 0 else "green"
            color_day = "red" if day_ret > 0 else "green"
            
            with st.container():
                # 第一行：股票名称和代码
                st.markdown(f"**{code} | {name}**")
                
                # 第二行：3列数据显示 (现价 | 日涨跌 | 月涨跌)
                col1, col2, col3 = st.columns([1.2, 1, 1])
                
                with col1:
                    st.write(f"¥{price:,.0f}")
                    st.caption(f"成本: ¥{cost:,.0f}")
                
                with col2:
                    st.markdown(f":{color_day}[{day_ret:+.2%}]")
                    st.caption("今日")
                    
                with col3:
                    st.markdown(f":{color_mon}[**{mon_ret:+.2%}**]")
                    st.caption("本月")
                
                st.divider()
    else:
        st.error("无法获取持仓数据，请检查代码是否正确")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 列表已保存到网址。")
