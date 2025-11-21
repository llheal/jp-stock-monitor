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

# --- 核心：Topix 获取逻辑 (三级容灾) ---
def get_topix_data_robust(month_start):
    """
    策略：
    1. 爬虫 (Yahoo Title) -> 失败?
    2. yfinance (^TOPX) -> 失败?
    3. yfinance (1306.T - ETF) -> 作为最终兜底，涨跌幅近似
    """
    price = None
    open_price = None
    source = "Init"

    # --- 方案 A: Yahoo JP 爬虫 (仅尝试 Title，成功率最高) ---
    try:
        url = "https://finance.yahoo.co.jp/quote/998405.T"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 200:
            # 针对 Title 进行正则匹配，这比 class 稳定得多
            # 网页 Title 通常是: "トピックス【998405.T】：2,600.50..."
            soup = BeautifulSoup(r.content, "html.parser")
            if soup.title:
                match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', soup.title.string)
                if match:
                    price = float(match.group(1).replace(',', ''))
                    source = "Yahoo! JP (Live)"
    except:
        pass

    # --- 方案 B: yfinance ^TOPX (指数本身) ---
    if price is None:
        try:
            t = yf.Ticker("^TOPX")
            # 尝试 fast_info
            if t.fast_info.last_price:
                price = t.fast_info.last_price
                source = "Yahoo Finance (^TOPX)"
            else:
                # 尝试 history
                hist = t.history(period="1d")
                if not hist.empty:
                    price = hist.iloc[-1]['Close']
                    source = "YF History (^TOPX)"
        except:
            pass

    # --- 方案 C: yfinance 1306.T (ETF 替身) ---
    # 如果指数彻底拿不到，我们用 ETF 的涨跌幅来近似
    use_etf_proxy = False
    if price is None:
        try:
            etf = yf.Ticker("1306.T") # 野村 TOPIX ETF
            if etf.fast_info.last_price:
                price = etf.fast_info.last_price
                source = "ETF Proxy (1306.T)"
                use_etf_proxy = True
        except:
            pass

    # --- 获取月初基准 (计算月涨跌用) ---
    # 必须与当前价的标的对应。如果是 ETF 替身，就要拿 ETF 的月初价。
    target_symbol = "1306.T" if use_etf_proxy else "^TOPX"
    
    try:
        hist_m = yf.Ticker(target_symbol).history(start=month_start, interval="1d")
        if not hist_m.empty:
            open_price = hist_m.iloc[0]['Open']
            # 终极兜底：如果当前价还是 None，就用历史最后收盘价
            if price is None:
                price = hist_m.iloc[-1]['Close']
                source = f"Historical Close ({target_symbol})"
    except:
        pass
        
    return price, open_price, source

# --- 主计算逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # 1. 获取 Topix (容灾版)
    tp_curr, tp_open, tp_src = get_topix_data_robust(month_start)
    
    if tp_curr and tp_open and tp_open > 0:
        topix_pct = (tp_curr - tp_open) / tp_open
    else:
        topix_pct = 0.0
        tp_curr = 0.0 # 避免 None 报错

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

    # 3. 个股处理
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
    with st.spinner('正在获取数据 (含容灾处理)...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val, tp_src = calculate_data(user_input, leverage)
    
    if not df.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        # 颜色: inverse (红涨绿跌)
        col1.metric(f"📊 组合收益 ({leverage}x)", f"{port_ret:+.2%}", 
                    delta=f"{port_ret:+.2%}", delta_color="inverse")
        
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", 
                    delta=f"{alpha:+.2%}", delta_color="inverse")
        
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}", 
                    delta=f"{nk_pct:+.2%}", delta_color="inverse")
        
        # Topix 逻辑处理
        if tp_val > 0:
            topix_str = f"{tp_pct:+.2%}"
            topix_delta = f"{tp_pct:+.2%}"
            topix_help = f"点数: {tp_val:,.2f}\n来源: {tp_src}"
            # 如果用了 ETF 替身，提示一下
            if "ETF Proxy" in tp_src:
                topix_help += "\n⚠️ 注意: 指数获取失败，使用 1306.T (ETF) 近似涨跌幅。"
        else:
            topix_str = "N/A"
            topix_delta = None
            topix_help = f"数据获取完全失败\n来源: {tp_src}"

        col4.metric("🇯🇵 Topix (月)", topix_str, 
                    delta=topix_delta, delta_color="inverse",
                    help=topix_help)
        
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
        
        # 底部状态栏
        st.caption(f"Topix 数据源状态: {tp_src}")
        
    else:
        st.error("无数据。")
