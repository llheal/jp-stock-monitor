import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股实盘监控", page_icon="📈", layout="centered")

# --- 1. 智能默认值 ---
FALLBACK_CODES = "7203, 9984, 8035" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏配置 ---
st.sidebar.header("⚙️ 监控配置")
# 用户输入区域
user_input = st.sidebar.text_area("输入代码 (逗号分隔)", value=initial_value, height=100)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)
st.sidebar.caption("提示：直接输入数字即可，如 7203，系统会自动识别为日股。")

# --- 核心函数：获取数据并正确计算涨跌 ---
def get_realtime_data(codes_str):
    # 1. 清洗代码：处理全角逗号，去除空格
    raw_codes = [c.strip() for c in codes_str.replace('，', ',').split(',') if c.strip()]
    
    # 2. 格式化代码：如果是纯数字，自动添加 .T 后缀 (针对日股)
    tickers = []
    for code in raw_codes:
        if code.isdigit():
            tickers.append(f"{code}.T")
        else:
            tickers.append(code) # 兼容其他格式，如 ^N225
            
    if not tickers:
        return pd.DataFrame()

    data_list = []
    
    # 3. 循环获取数据 (利用 yfinance 的 fast_info 获取实时/准实时数据)
    # 进度条 (可选，代码多时有用)
    progress_bar = st.progress(0)
    
    for i, ticker_symbol in enumerate(tickers):
        try:
            stock = yf.Ticker(ticker_symbol)
            # fast_info 是 yfinance 获取元数据最快的方式
            info = stock.fast_info
            
            current_price = info.last_price
            prev_close = info.previous_close
            
            # --- 关键修复逻辑 ---
            # 只有拿到“昨日收盘价”，计算出的涨跌幅才是今日真实的涨跌
            if prev_close and prev_close > 0:
                change_amount = current_price - prev_close
                change_pct = (change_amount / prev_close) * 100
            else:
                change_amount = 0
                change_pct = 0
            
            data_list.append({
                "代码": ticker_symbol.replace('.T', ''), # 展示时去掉后缀更美观
                "当前价": current_price,
                "昨日收盘": prev_close,
                "涨跌额": change_amount,
                "涨跌幅": change_pct / 100 # 存为小数，后面用 format 格式化为百分比
            })
        except Exception as e:
            # 仅在控制台打印错误，不打断界面
            print(f"Error fetching {ticker_symbol}: {e}")
            
        # 更新进度条
        progress_bar.progress((i + 1) / len(tickers))

    progress_bar.empty() # 隐藏进度条
    return pd.DataFrame(data_list)

# --- 主界面布局 ---
st.title("🇯🇵 日股实盘看板")
st.caption(f"最后刷新时间: {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')} (JST)")

# 刷新按钮
if st.button("🔄 立即刷新", use_container_width=True):
    with st.spinner('正在从交易所获取数据...'):
        df = get_realtime_data(user_input)
    
    if not df.empty:
        # --- 数据展示与样式 ---
        # 定义样式函数：正数红色，负数绿色 (符合日股/A股习惯，若习惯美股可反过来)
        def color_change(val):
            if val > 0:
                return 'color: #d32f2f; font-weight: bold' # 红
            elif val < 0:
                return 'color: #2e7d32; font-weight: bold' # 绿
            return 'color: gray'

        # 应用样式
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "昨日收盘": "{:,.1f}",
            "涨跌额": "{:+.1f}",
            "涨跌幅": "{:+.2%}"
        }).map(color_change, subset=['涨跌额', '涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # 简单的行情概览
        avg_change = df["涨跌幅"].mean()
        st.info(f"📉 平均涨跌幅: {avg_change:.2%}")
        
    else:
        st.warning("⚠️ 未能获取数据，请检查代码拼写或网络连接。")

# --- 侧边栏说明 ---
st.sidebar.markdown("---")
st.sidebar.markdown("""
**计算逻辑说明：**
* **涨跌额** = 当前价 - 昨日收盘价
* **涨跌幅** = (涨跌额 / 昨日收盘价) %
* 数据源：Yahoo Finance API
""")
