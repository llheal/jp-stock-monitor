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

# --- 核心爬虫：Minkabu ---
def get_topix_minkabu():
    """
    Target: <div class="stock_price">3,289.<span class="decimal">64</span></div>
    """
    url = "https://minkabu.jp/stock/KSISU1000"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            price_div = soup.find("div", class_="stock_price")
            if price_div:
                raw_text = price_div.get_text(strip=True)
                clean_text = raw_text.replace('\n', '').replace(' ', '').replace(',', '')
                return float(clean_text)
    except Exception:
        pass
    return None

# --- 核心：获取 Topix 数据 (含 ETF 替身逻辑) ---
def get_topix_data_robust(month_start):
    # 1. 获取实时点数 (Minkabu)
    current_price = get_topix_minkabu()
    source = "Minkabu (Live)"
    
    # 备份: 如果 Minkabu 挂了，试一下 yfinance
    if current_price is None:
        try:
            t = yf.Ticker("^TOPX")
            if t.fast_info.last_price:
                current_price = t.fast_info.last_price
                source = "Yahoo Finance (Backup)"
        except:
            pass

    # 2. 计算月度涨跌幅
    # 优先使用指数自身的历史数据
    pct_change = 0.0
    calc_method = "Index History"
    
    has_index_history = False
    try:
        hist = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
        if not hist.empty:
            month_open = hist.iloc[0]['Open']
            # 如果没抓到实时价，就用历史收盘价兜底
            if current_price is None:
                current_price = hist.iloc[-1]['Close']
                source = "Historical Close"
            
            if current_price:
                pct_change = (current_price - month_open) / month_open
                has_index_history = True
    except:
        pass

    # 3. 如果指数历史数据获取失败 (关键修复)
    # 使用 ETF (1306.T) 的涨跌幅作为“替身”
    if not has_index_history:
        try:
            etf = yf.Ticker("1306.T")
            hist_etf = etf.history(start=month_start, interval="1d")
            if not hist_etf.empty:
                etf_open = hist_etf.iloc[0]['Open']
                etf_curr = etf.fast_info.last_price if etf.fast_info.last_price else hist_etf.iloc[-1]['Close']
                
                pct_change = (etf_curr - etf_open) / etf_open
                calc_method = "ETF Proxy (1306.T)"
                
                # 如果这时候 current_price 还是 None，说明所有源都挂了
        except:
            calc_method = "Failed"

    return current_price, pct_change, source, calc_method

# --- 主计算逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # 1. 获取 Topix
    tp_curr, tp_pct, tp_src, tp_method = get_topix_data_robust(month_start)
    
    # 2. 获取日经225
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
        
    alpha = leveraged_port_return - tp_pct
    
    return pd.DataFrame(table_rows), leveraged_port_return, alpha, nikkei_pct, tp_pct, tp_curr, tp_src, tp_method

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val, tp_src, tp_method = calculate_data(user_input, leverage)
    
    if not df.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric(f"📊 组合收益 ({leverage}x)", f"{port_ret:+.2%}", 
                    delta=f"{port_ret:+.2%}", delta_color="inverse")
        
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", 
                    delta=f"{alpha:+.2%}", delta_color="inverse")
        
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}", 
                    delta=f"{nk_pct:+.2%}", delta_color="inverse")
        
        # Topix 显示逻辑
        # 即使 tp_val 存在，tp_pct 也可能是用 ETF 算出来的
        if tp_val is not None:
            topix_help = f"当前点数: {tp_val:,.2f}\n来源: {tp_src}\n涨跌幅计算: {tp_method}"
            col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", 
                        delta=f"{tp_pct:+.2%}", delta_color="inverse",
                        help=topix_help)
        else:
            col4.metric("🇯🇵 Topix (月)", "N/A", help="无法获取数据")
        
        st.divider()
        
        # 表格
        st.caption("📋 个股表现 (原始涨跌幅)")
        def color_arrow(val):
            if val > 0: return 'color: #d32f2f; font-weight: bold'
            elif val < 0: return 'color: #2e7d32; font-weight: bold'
            return 'color: gray'

        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(color_arrow, subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
    else:
        st.error("无数据。")
