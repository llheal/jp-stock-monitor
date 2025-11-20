import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股策略监控", page_icon="📱")

# --- 侧边栏：输入你的持仓 ---
# 因为电脑关机了，云端不知道你买了啥，所以你需要每个月手动把代码贴在这里一次
# 或者写死在代码里
st.sidebar.header("⚙️ 持仓配置")
default_codes = "7203, 9984, 8035, 6758, 6861" # 示例代码
user_input = st.sidebar.text_area("输入股票代码 (逗号或换行分隔)", value=default_codes, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心逻辑 ---
def get_stock_data(codes):
    data_list = []
    
    # 获取当前东京时间
    jp_tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jp_tz)
    
    # 确定本月第一天
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_str = start_of_month.strftime('%Y-%m-%d')
    
    # 进度条
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        
        # yfinance 日股代码需要加 .T
        ticker_symbol = f"{code}.T" if not code.endswith(".T") else code
        
        try:
            # 获取数据：从本月1号到现在
            stock = yf.Ticker(ticker_symbol)
            # interval='1d' 获取日线，'1m' 获取实时(可能有延迟)
            # 为了速度和稳定性，我们要两部分：
            # 1. 历史日线 (找月初开盘价)
            hist = stock.history(start=start_str, interval="1d")
            
            if hist.empty:
                # 如果月初是假期，yfinance可能没数据，尝试多取几天
                hist = stock.history(period="1mo", interval="1d")
            
            # 获取实时价格 (ask/bid/regularMarketPrice)
            # yfinance 的 info 经常请求慢，我们尝试用 fast_info 或 history 的最后一行
            current_price = 0.0
            
            # 尝试获取最新一分钟数据作为实时价
            todays_data = stock.history(period="1d", interval="5m")
            if not todays_data.empty:
                current_price = todays_data['Close'].iloc[-1]
            else:
                # 如果盘前或获取失败，用最后收盘价
                current_price = hist['Close'].iloc[-1]
            
            # 获取月初买入价 (本月第一条数据的 Open)
            # 过滤掉今天 (如果今天是1号，那就取今天的Open)
            # 这里的逻辑取 hist 的第一行 Open
            buy_price = hist.iloc[0]['Open']
            buy_date = hist.index[0].strftime('%m-%d')
            
            ret = (current_price - buy_price) / buy_price
            
            data_list.append({
                "代码": code,
                "买入日": buy_date,
                "买入价": buy_price,
                "现价": current_price,
                "收益率": ret
            })
            
        except Exception as e:
            st.error(f"{code} 获取失败: {e}")
        
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 显示界面 ---
st.title("📱 策略实盘监控")

# 处理输入的代码
codes_to_check = [c.strip() for c in user_input.replace('\n', ',').split(',') if c.strip()]

if st.button("🔄 刷新数据", type="primary", use_container_width=True):
    if not codes_to_check:
        st.warning("请输入股票代码")
    else:
        df = get_stock_data(codes_to_check)
        
        if not df.empty:
            # 总体收益
            avg_ret = df['收益率'].mean()
            total_ret = avg_ret * leverage
            
            # 大字显示
            st.metric("组合总收益 (杠杆后)", f"{total_ret:.2%}", 
                      delta_color="normal" if total_ret > 0 else "inverse")
            
            st.markdown("---")
            
            # 排序
            df = df.sort_values(by='收益率', ascending=False)
            
            # 手机端卡片式显示
            for _, row in df.iterrows():
                c_code = row['代码']
                c_ret = row['收益率']
                c_price = row['现价']
                c_buy = row['买入价']
                
                color = "green" if c_ret > 0 else "red"
                
                with st.container():
                    col1, col2, col3 = st.columns([2, 2, 2])
                    col1.markdown(f"**{c_code}**")
                    col2.write(f"¥{c_price:,.0f}")
                    col3.markdown(f":{color}[{c_ret:+.2%}]")
                    st.caption(f"成本: ¥{c_buy:,.0f} ({row['买入日']})")
                    st.divider()