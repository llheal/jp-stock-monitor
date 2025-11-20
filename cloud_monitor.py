import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股策略监控", page_icon="📱")

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

def get_current_price(ticker_symbol):
    """获取最新的实时价格 (兼容盘中和盘后)"""
    try:
        stock = yf.Ticker(ticker_symbol)
        # 尝试获取盘中 5分钟级 数据
        todays_data = stock.history(period="1d", interval="5m")
        if not todays_data.empty:
            return todays_data['Close'].iloc[-1]
        
        # 如果获取不到盘中数据(比如周末)，获取最近日线收盘价
        recent_data = stock.history(period="5d")
        if not recent_data.empty:
            return recent_data['Close'].iloc[-1]
    except:
        pass
    return 0.0

def fetch_index_data(ticker_symbol, start_str):
    """
    获取指数的三重数据：
    1. 当前点位/价格
    2. 当日涨跌 (Daily Return)
    3. 本月涨跌 (MTD Return)
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # A. 获取最近5天日线 (用于计算当日涨跌)
        hist_recent = stock.history(period="5d")
        
        # B. 获取本月历史 (用于计算本月涨跌)
        hist_mtd = stock.history(start=start_str)
        if hist_mtd.empty:
             hist_mtd = stock.history(period="1mo")

        # C. 获取实时价格
        current_price = get_current_price(ticker_symbol)
        # 如果实时获取失败，尝试用历史最后一天
        if current_price == 0 and not hist_recent.empty:
            current_price = hist_recent['Close'].iloc[-1]

        # --- 计算当日收益 (Daily) ---
        daily_ret = 0.0
        # 昨收价：倒数第2天的收盘价 
        if len(hist_recent) >= 2:
            prev_close = hist_recent['Close'].iloc[-2]
            if prev_close > 0:
                daily_ret = (current_price - prev_close) / prev_close
        
        # --- 计算本月收益 (MTD) ---
        mtd_ret = 0.0
        if not hist_mtd.empty:
            # 月初开盘价
            month_open = hist_mtd.iloc[0]['Open']
            if month_open > 0:
                mtd_ret = (current_price - month_open) / month_open

        return {
            "daily_ret": daily_ret,
            "mtd_ret": mtd_ret,
            "price": current_price,
            "valid": True
        }
    except Exception as e:
        return {"valid": False}

def fetch_stock_data(codes, start_str):
    """获取持仓股票数据"""
    data_list = []
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        
        # 处理 .T 后缀
        ticker_symbol = f"{code}.T" if not code.endswith(".T") else code
        
        try:
            stock = yf.Ticker(ticker_symbol)
            # 1. 历史数据 (找月初)
            hist = stock.history(start=start_str)
            if hist.empty:
                hist = stock.history(period="1mo")
            
            # 2. 实时价格
            current_price = get_current_price(ticker_symbol)
            if current_price == 0 and not hist.empty:
                current_price = hist['Close'].iloc[-1]
            
            # 3. 月初成本
            buy_price = 0
            buy_date = "N/A"
            if not hist.empty:
                buy_price = hist.iloc[0]['Open']
                buy_date = hist.index[0].strftime('%m-%d')
            
            # 避免除以零
            if buy_price > 0:
                ret = (current_price - buy_price) / buy_price
            else:
                ret = 0.0
            
            data_list.append({
                "代码": code,
                "买入日": buy_date,
                "买入价": buy_price,
                "现价": current_price,
                "收益率": ret
            })
        except:
            pass
        
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主程序逻辑 ---

# 1. 确定时间
jp_tz = pytz.timezone('Asia/Tokyo')
now = datetime.now(jp_tz)
# 确保时区一致性
start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
start_str = start_of_month.strftime('%Y-%m-%d')

st.title("📱 日股实盘监控")

# 处理持仓列表
clean_codes_list = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_codes_str = ",".join(clean_codes_list)

if st.button("🔄 刷新行情", type="primary", use_container_width=True):
    # 更新 URL
    st.query_params["codes"] = clean_codes_str
    
    # 1. 获取大盘指数
    nikkei_data = fetch_index_data("^N225", start_str)
    topix_data = fetch_index_data("1306.T", start_str)
    
    # 2. 获取个股持仓
    df = fetch_stock_data(clean_codes_list, start_str)
    
    # --- 界面显示部分 ---

    # A. 市场概况卡片
    st.caption(f"📊 市场概况 (东京时间 {now.strftime('%H:%M')})")
    
    idx_c1, idx_c2 = st.columns(2)
    
    with idx_c1:
        if nikkei_data["valid"]:
            # Value: 具体点位
            # Delta: 当日涨跌
            # Label: 指数名 + (本月涨跌)
            st.metric(
                label=f"日经 225 (本月 {nikkei_data['mtd_ret']:+.1%})",
                value=f"{nikkei_data['price']:,.2f}", 
                delta=f"{nikkei_data['daily_ret']:+.2%} 今日",
                delta_color="normal"
            )
        else:
            st.metric("日经 225", "获取失败")
            
    with idx_c2:
        if topix_data["valid"]:
            # TOPIX 使用 ETF 价格
            st.metric(
                label=f"TOPIX ETF (本月 {topix_data['mtd_ret']:+.1%})",
                value=f"{topix_data['price']:,.0f}", 
                delta=f"{topix_data['daily_ret']:+.2%} 今日",
                delta_color="normal"
            )
        else:
            st.metric("TOPIX", "获取失败")

    st.markdown("---")

    # B. 策略表现卡片
    if not df.empty:
        avg_ret = df['收益率'].mean()
        total_ret = avg_ret * leverage
        
        # 计算 Alpha (策略本月收益 - TOPIX 本月收益)
        alpha = 0.0
        if topix_data["valid"]:
            alpha = total_ret - topix_data['mtd_ret']

        st.caption("📈 策略表现 (本月累计)")
        strat_c1, strat_c2 = st.columns(2)
        
        with strat_c1:
            st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", 
                      delta_color="normal" if total_ret > 0 else "inverse")
        with strat_c2:
            st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}",
                      delta_color="off")

        st.divider()
        
        # C. 个股详情列表
        st.subheader("持仓详情")
        df = df.sort_values(by='收益率', ascending=False)
        
        for _, row in df.iterrows():
            c_code = row['代码']
            c_ret = row['收益率']
            c_price = row['现价']
            
            # 简单配色：涨红跌绿
            color = "red" if c_ret > 0 else "green"
            
            with st.container():
                c1, c2, c3 = st.columns([2, 2, 2])
                c1.markdown(f"**{c_code}**")
                c2.write(f"¥{c_price:,.0f}")
                c3.markdown(f":{color}[{c_ret:+.2%}]")
                st.divider()
    else:
        if not clean_codes_list:
            st.info("请在侧边栏输入代码")
        else:
            st.error("持仓数据获取失败")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 提示：列表已保存到网址，请收藏当前页面。")
