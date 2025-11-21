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
FALLBACK_CODES = "7203, 9984, 8035" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")
st.sidebar.caption("提示：假设每只股票持仓金额相等（等权重）。")
user_input = st.sidebar.text_area("持仓列表 (代码,代码...)", value=initial_value, height=150)

# --- 辅助函数 ---
def get_month_start_date():
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

# --- 爬虫：专门针对 Topix (998405.T) ---
def get_topix_realtime_yahoo_jp():
    """
    直接爬取 Yahoo!ファイナンス 网页获取 TOPIX 实时点数
    """
    url = "https://finance.yahoo.co.jp/quote/998405.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code != 200: return None
        
        soup = BeautifulSoup(r.content, "html.parser")
        title_text = soup.title.string if soup.title else ""
        
        # 正则提取冒号后面的数字
        match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', title_text)
        if match:
            return float(match.group(1).replace(',', ''))
        return None
    except Exception:
        return None

# --- 核心逻辑 ---
def calculate_data(user_input_str):
    month_start = get_month_start_date()
    
    # 1. 准备指数数据
    # A. 日经225
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

    # B. TOPIX
    topix_pct = 0.0
    topix_current = get_topix_realtime_yahoo_jp() # 爬取实时
    
    try:
        # 用 yfinance 获取月初历史数据
        tp_hist = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
        if not tp_hist.empty:
            topix_open = tp_hist.iloc[0]['Open']
            # 如果爬虫失败，用历史收盘价兜底
            if topix_current is None:
                topix_current = tp_hist.iloc[-1]['Close']
            
            # 只有当 topix_current 有值时才计算
            if topix_current:
                topix_pct = (topix_current - topix_open) / topix_open
    except:
        pass

    # 2. 计算个股数据
    raw_items = [x.strip() for x in user_input_str.replace('，', ',').split(',') if x.strip()]
    
    individual_returns = [] # 存储每只股票的月收益率
    table_rows = []
    
    bar = st.progress(0)
    
    for i, item in enumerate(raw_items):
        try:
            parts = item.split(':')
            code = parts[0].strip()
            
            yf_ticker = f"{code}.T" if code.isdigit() else code
            stock = yf.Ticker(yf_ticker)
            
            # 获取价格
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            hist = stock.history(start=month_start, interval="1d")
            
            if not hist.empty and current_price:
                month_open = hist.iloc[0]['Open']
                # 安全除法
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
        bar.progress((i + 1) / len(raw_items))
        
    bar.empty()
    
    # 3. 计算组合总收益率 (简单平均值)
    if individual_returns:
        port_return = sum(individual_returns) / len(individual_returns)
    else:
        port_return = 0.0
        
    # 4. Alpha
    alpha = port_return - topix_pct
    
    return pd.DataFrame(table_rows), port_return, alpha, nikkei_pct, topix_pct, topix_current

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算等权收益率...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val = calculate_data(user_input)
    
    if not df.empty:
        # --- 指标卡片 ---
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("📊 组合平均收益", f"{port_ret:+.2%}", help="计算方式：所有持仓股票月涨跌幅的平均值")
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", delta_color="normal" if alpha > 0 else "inverse")
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}")
        
        # --- 关键修复点 ---
        # 判断 tp_val 是否为 None，防止格式化报错
        if tp_val is not None:
            topix_help = f"当前点数: {tp_val:,.2f} (来源: Yahoo! JP)"
        else:
            topix_help = "当前点数: N/A (获取失败)"
            
        col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", help=topix_help)
        
        st.divider()
        
        # --- 表格 ---
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
               subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.error("无数据。")
