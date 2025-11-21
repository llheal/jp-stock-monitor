import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re

# --- 页面配置 ---
st.set_page_config(page_title="日股Alpha监控", page_icon="🇯🇵", layout="wide")

# --- 1. 配置区域 ---
FALLBACK_CODES = """7203
9984
8035"""

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")
leverage = st.sidebar.number_input("杠杆倍数 (x)", min_value=0.1, max_value=10.0, value=1.5, step=0.1)
st.sidebar.caption("输入方式：每行一个代码")
user_input = st.sidebar.text_area("持仓代码列表", value=initial_value, height=300)

# --- 辅助函数 ---
def get_month_start_date():
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

# --- 核心爬虫：Kabutan (株探) ---
def get_topix_kabutan():
    """
    从 Kabutan 爬取 Topix (代码 0010)
    URL: https://kabutan.jp/stock/?code=0010
    """
    url = "https://kabutan.jp/stock/?code=0010"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            
            # Kabutan 的价格通常在 span class="kabuka" 中
            # 结构: <span class="kabuka">2,698.50</span>
            price_span = soup.find("span", class_="kabuka")
            
            if price_span:
                price_str = price_span.text.strip().replace(",", "")
                return float(price_str)
                
    except Exception as e:
        print(f"Kabutan Error: {e}")
        return None
    return None

# --- 综合数据获取 ---
def get_topix_data_combined(month_start):
    # 1. 优先尝试 Kabutan (轻量，成功率高)
    current_price = get_topix_kabutan()
    source = "Kabutan (Live)"
    
    # 2. 失败则回退到 yfinance ^TOPX
    if current_price is None:
        try:
            t = yf.Ticker("^TOPX")
            fi = t.fast_info
            if fi.last_price:
                current_price = fi.last_price
                source = "Yahoo Finance (Backup)"
            else:
                hist = t.history(period="1d")
                if not hist.empty:
                    current_price = hist.iloc[-1]['Close']
                    source = "Historical Close (Delayed)"
        except:
            pass

    # 3. 获取月初开盘 (始终用 yfinance 历史数据)
    month_open = None
    try:
        hist = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
        if not hist.empty:
            month_open = hist.iloc[0]['Open']
            # 终极兜底
            if current_price is None:
                current_price = hist.iloc[-1]['Close']
    except:
        pass
        
    return current_price, month_open, source

# --- 核心计算逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # 1. Topix
    tp_curr, tp_open, tp_src = get_topix_data_combined(month_start)
    
    if tp_curr and tp_open and tp_open > 0:
        topix_pct = (tp_curr - tp_open) / tp_open
    else:
        topix_pct = 0.0
        tp_curr = 0.0

    # 2. 日经225
    nikkei_pct = 0.0
    try:
        nk = yf.Ticker("^N225")
        nk_hist = nk.history(start=month_start, interval="1d")
        if not nk_hist.empty:
            nk_curr = nk_hist.iloc[-1]['Close']
            nk_open = nk_hist.iloc[0]['Open']
            nikkei_pct = (nk_curr - nk_open) / nk_open
    except:
        pass

    # 3. 个股
    raw_items = [x.strip() for x in re.split(r'[,\n]', user_input_str) if x.strip()]
    individual_returns = [] 
    table_rows = []
    
    bar = st.progress(0)
    
    for i, item in enumerate(raw_items):
        try:
            code = item.split(':')[0].strip()
            yf_ticker = f"{code}.T" if code.isdigit() else code
            stock = yf.Ticker(yf_ticker)
            
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            hist = stock.history(start=month_start, interval="1d")
            
            if not hist.empty and current_price:
                month_open = hist.iloc[0]['Open']
                day_change = (current_price - prev_close) / prev_close if prev_close else 0
                month_change = (current_price - month_open) / month_open if month_open else 0
            else:
                month_open = prev_close
                day_change = 0.0
                month_change = 0.0
            
            individual_returns.append(month_change)
            
            table_rows.append({
                "代码": code,
                "当前价": current_price,
                "日涨跌幅": day_change,
                "月涨跌幅": month_change
            })
        except:
            pass 
        bar.progress((i + 1) / max(len(raw_items), 1))
        
    bar.empty()
    
    # 4. 组合计算
    if individual_returns:
        avg_return = sum(individual_returns) / len(individual_returns)
        leveraged_port_return = avg_return * leverage_ratio
    else:
        leveraged_port_return = 0.0
        
    alpha = leveraged_port_return - topix_pct
    
    return pd.DataFrame(table_rows), leveraged_port_return, alpha, nikkei_pct, topix_pct, tp_curr, tp_src

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在从 Kabutan (株探) 获取数据...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val, tp_src = calculate_data(user_input, leverage)
    
    if not df.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        # 颜色逻辑: inverse (红涨绿跌)
        col1.metric(f"📊 组合收益 ({leverage}x)", f"{port_ret:+.2%}", 
                    delta=f"{port_ret:+.2%}", delta_color="inverse")
        
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", 
                    delta=f"{alpha:+.2%}", delta_color="inverse")
        
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}", 
                    delta=f"{nk_pct:+.2%}", delta_color="inverse")
        
        # Topix 显示
        col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", 
                    delta=f"{tp_pct:+.2%}", delta_color="inverse",
                    help=f"点数: {tp_val:,.2f}\n来源: {tp_src}")
        
        st.divider()
        
        # 表格
        st.caption("📋 个股表现 (原始涨跌幅)")
        
        def color_arrow(val):
            if val > 0:
                return 'color: #d32f2f; font-weight: bold' # Red
            elif val < 0:
                return 'color: #2e7d32; font-weight: bold' # Green
            return 'color: gray'

        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(color_arrow, subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
    else:
        st.error("无法获取数据。")
