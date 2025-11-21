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
# 默认值改为换行格式，方便演示
FALLBACK_CODES = """7203
9984
8035"""

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")

# 1. 杠杆设置
leverage = st.sidebar.number_input("杠杆倍数 (x)", min_value=0.1, max_value=10.0, value=1.5, step=0.1, help="组合总收益 = 股票平均收益 × 杠杆倍数")

# 2. 代码输入 (支持换行)
st.sidebar.caption("输入方式：每行一个代码，或者用逗号分隔。")
user_input = st.sidebar.text_area("持仓代码列表", value=initial_value, height=300)

# --- 辅助函数 ---
def get_month_start_date():
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

# --- 爬虫：Topix (998405.T) ---
def get_topix_realtime_yahoo_jp():
    url = "https://finance.yahoo.co.jp/quote/998405.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.content, "html.parser")
        title_text = soup.title.string if soup.title else ""
        match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', title_text)
        if match:
            return float(match.group(1).replace(',', ''))
        return None
    except Exception:
        return None

# --- 核心逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
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
    topix_current = get_topix_realtime_yahoo_jp()
    
    try:
        tp_hist = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
        if not tp_hist.empty:
            topix_open = tp_hist.iloc[0]['Open']
            if topix_current is None:
                topix_current = tp_hist.iloc[-1]['Close']
            
            if topix_current:
                topix_pct = (topix_current - topix_open) / topix_open
    except:
        pass

    # 2. 解析用户输入 (支持换行 \n 和逗号 ,)
    # 使用正则 re.split 同时按照 逗号 和 换行符 分割
    raw_items = [x.strip() for x in re.split(r'[,\n]', user_input_str) if x.strip()]
    
    individual_returns = [] 
    table_rows = []
    
    bar = st.progress(0)
    
    for i, item in enumerate(raw_items):
        try:
            # 依然兼容 "代码:股数" 格式，但只取代码
            parts = item.split(':')
            code = parts[0].strip()
            
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
        bar.progress((i + 1) / len(raw_items))
        
    bar.empty()
    
    # 3. 计算组合总收益
    if individual_returns:
        raw_avg_return = sum(individual_returns) / len(individual_returns)
        # --- 应用杠杆 ---
        leveraged_port_return = raw_avg_return * leverage_ratio
    else:
        leveraged_port_return = 0.0
        
    # 4. Alpha (杠杆后的组合收益 - Topix)
    alpha = leveraged_port_return - topix_pct
    
    return pd.DataFrame(table_rows), leveraged_port_return, alpha, nikkei_pct, topix_pct, topix_current

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val = calculate_data(user_input, leverage)
    
    if not df.empty:
        # --- 指标卡片 ---
        col1, col2, col3, col4 = st.columns(4)
        
        # 显示杠杆倍数提示
        col1.metric(f"📊 组合收益 ({leverage}x)", f"{port_ret:+.2%}", help="已乘以杠杆倍数")
        
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", delta_color="normal" if alpha > 0 else "inverse")
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}")
        
        if tp_val is not None:
            topix_help = f"当前点数: {tp_val:,.2f} (来源: Yahoo! JP)"
        else:
            topix_help = "Topix N/A"
        col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", help=topix_help)
        
        st.divider()
        
        # --- 表格 ---
        st.caption("📋 个股表现 (显示为原始涨跌幅，不含杠杆)")
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
               subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.error("无数据，请检查输入。")
