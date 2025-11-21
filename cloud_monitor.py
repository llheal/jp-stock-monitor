import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股Alpha监控", page_icon="🇯🇵", layout="wide")

# --- 1. 配置区域 ---
FALLBACK_CODES = "7203:100, 9984:200, 8035:100" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")
st.sidebar.caption("格式：代码:股数 (用于计算加权收益率，股数不会显示在界面上)。")
user_input = st.sidebar.text_area("持仓列表", value=initial_value, height=150)

# --- 辅助函数 ---
def get_month_start_date():
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

# --- 核心逻辑 ---
def calculate_data(user_input_str):
    month_start = get_month_start_date()
    
    # 1. 获取指数数据 (Nikkei & Topix)
    # ^N225: 日经, 998405.T: Topix (按用户指定)
    indices_map = {
        "Nikkei 225": "^N225",
        "Topix": "998405.T" 
    }
    indices_data = {}
    
    for name, ticker_code in indices_map.items():
        try:
            idx = yf.Ticker(ticker_code)
            # 获取历史数据以计算月度
            hist = idx.history(start=month_start, interval="1d")
            if not hist.empty:
                current = hist.iloc[-1]['Close'] # 使用最新的收盘或当前价
                open_price = hist.iloc[0]['Open']
                pct = (current - open_price) / open_price
                indices_data[name] = pct
            else:
                # 如果 998405.T 获取失败，尝试备用代码 ^TOPX (仅针对 Topix)
                if name == "Topix":
                    backup = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
                    if not backup.empty:
                        current = backup.iloc[-1]['Close']
                        open_price = backup.iloc[0]['Open']
                        pct = (current - open_price) / open_price
                        indices_data[name] = pct
                    else:
                        indices_data[name] = 0.0
                else:
                    indices_data[name] = 0.0
        except:
            indices_data[name] = 0.0

    # 2. 解析用户持仓
    raw_items = [x.strip() for x in user_input_str.replace('，', ',').split(',') if x.strip()]
    portfolio = []
    
    total_current_val = 0.0
    total_open_val = 0.0
    
    table_rows = []
    
    # 进度条
    bar = st.progress(0)
    
    for i, item in enumerate(raw_items):
        try:
            parts = item.split(':')
            code = parts[0].strip()
            # 默认100股，仅用于后台计算权重，不显示
            shares = float(parts[1]) if len(parts) > 1 else 100.0 
            
            yf_ticker = f"{code}.T" if code.isdigit() else code
            
            stock = yf.Ticker(yf_ticker)
            
            # 获取数据
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            hist = stock.history(start=month_start, interval="1d")
            if not hist.empty:
                month_open = hist.iloc[0]['Open']
            else:
                month_open = prev_close
            
            # 计算
            val_current = current_price * shares
            val_open = month_open * shares
            
            total_current_val += val_current
            total_open_val += val_open
            
            day_change = (current_price - prev_close) / prev_close if prev_close else 0
            month_change = (current_price - month_open) / month_open if month_open else 0
            
            table_rows.append({
                "代码": code,
                "当前价": current_price,
                "日涨跌幅": day_change,
                "月涨跌幅": month_change
            })
            
        except Exception as e:
            pass
        
        bar.progress((i + 1) / len(raw_items))
        
    bar.empty()
    
    # 3. 计算组合总收益率
    if total_open_val > 0:
        port_return = (total_current_val - total_open_val) / total_open_val
    else:
        port_return = 0.0
        
    # 4. 计算 Alpha (组合 - Topix)
    alpha = port_return - indices_data.get("Topix", 0.0)
    
    return pd.DataFrame(table_rows), port_return, alpha, indices_data

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算收益率...'):
        df, port_ret, alpha, indices = calculate_data(user_input)
    
    if not df.empty:
        # --- 1. 纯百分比指标卡片 ---
        col1, col2, col3, col4 = st.columns(4)
        
        # 组合收益
        col1.metric("📊 组合月收益", f"{port_ret:+.2%}")
        
        # Alpha
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", 
                    delta_color="normal" if alpha > 0 else "inverse")
        
        # 指数参照
        col3.metric("🇯🇵 日经225 (月)", f"{indices['Nikkei 225']:+.2%}")
        col4.metric("🇯🇵 Topix (月)", f"{indices['Topix']:+.2%}")
        
        st.divider()
        
        # --- 2. 表格 (只含价格与百分比) ---
        # 样式设置
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
               subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
            
    else:
        st.error("未获取到数据，请检查代码或网络。")
