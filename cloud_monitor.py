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

# --- 爬虫：Topix (带备选方案) ---
def get_topix_data(month_start):
    """
    尝试获取 Topix 的当前价和月初开盘价
    策略：Yahoo Japan 爬虫 -> 失败则转 yfinance ^TOPX
    """
    current_price = None
    
    # 方案 A: 爬取 Yahoo Japan (实时性最好，但容易被云服务器屏蔽)
    url = "https://finance.yahoo.co.jp/quote/998405.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://finance.yahoo.co.jp/"
    }
    source = "Yahoo! JP"
    
    try:
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            title_text = soup.title.string if soup.title else ""
            match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', title_text)
            if match:
                current_price = float(match.group(1).replace(',', ''))
    except:
        pass

    # 方案 B: 如果爬虫失败，使用 yfinance ^TOPX (可能有延迟)
    if current_price is None:
        try:
            source = "Yahoo Finance (Delay)"
            topix_ticker = yf.Ticker("^TOPX")
            fi = topix_ticker.fast_info
            if fi.last_price:
                current_price = fi.last_price
            else:
                # 再拿不到，就拿历史数据最后一行
                hist = topix_ticker.history(period="1d")
                if not hist.empty:
                    current_price = hist.iloc[-1]['Close']
        except:
            pass

    # 获取月初开盘价 (始终用 ^TOPX 历史数据，比较稳)
    month_open = None
    try:
        hist_month = yf.Ticker("^TOPX").history(start=month_start, interval="1d")
        if not hist_month.empty:
            month_open = hist_month.iloc[0]['Open']
            # 如果当前价彻底获取失败，就用历史收盘价兜底，防止报错
            if current_price is None:
                current_price = hist_month.iloc[-1]['Close']
                source = "Historical Close"
    except:
        pass
        
    return current_price, month_open, source

# --- 核心逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # 1. 获取 Topix 数据
    tp_curr, tp_open, tp_source = get_topix_data(month_start)
    if tp_curr and tp_open:
        topix_pct = (tp_curr - tp_open) / tp_open
    else:
        topix_pct = 0.0
        tp_curr = 0.0

    # 2. 获取日经225 (对比用)
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

    # 3. 解析用户持仓
    # 支持换行符 \n 和逗号分隔
    raw_items = [x.strip() for x in re.split(r'[,\n]', user_input_str) if x.strip()]
    
    individual_returns = [] 
    table_rows = []
    
    bar = st.progress(0)
    
    for i, item in enumerate(raw_items):
        try:
            # 兼容代码:股数格式，取冒号前部分
            code = item.split(':')[0].strip()
            
            yf_ticker = f"{code}.T" if code.isdigit() else code
            stock = yf.Ticker(yf_ticker)
            
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            # 获取本月历史数据
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
    
    # 4. 计算组合 (简单平均 * 杠杆)
    if individual_returns:
        avg_return = sum(individual_returns) / len(individual_returns)
        leveraged_port_return = avg_return * leverage_ratio
    else:
        leveraged_port_return = 0.0
        
    # 5. Alpha
    alpha = leveraged_port_return - topix_pct
    
    return pd.DataFrame(table_rows), leveraged_port_return, alpha, nikkei_pct, topix_pct, tp_curr, tp_source

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算数据...'):
        df, port_ret, alpha, nk_pct, tp_pct, tp_val, tp_src = calculate_data(user_input, leverage)
    
    if not df.empty:
        col1, col2, col3, col4 = st.columns(4)
        
        # --- 颜色说明 ---
        # st.metric 的 delta_color="inverse" 表示：
        # 正数 (Delta > 0) -> 红色 (Red) -> 涨
        # 负数 (Delta < 0) -> 绿色 (Green) -> 跌
        
        col1.metric(f"📊 组合收益 ({leverage}x)", f"{port_ret:+.2%}", 
                    delta=f"{port_ret:+.2%}", delta_color="inverse")
        
        col2.metric("🚀 Alpha (vs Topix)", f"{alpha:+.2%}", 
                    delta=f"{alpha:+.2%}", delta_color="inverse")
        
        col3.metric("🇯🇵 日经225 (月)", f"{nk_pct:+.2%}", 
                    delta=f"{nk_pct:+.2%}", delta_color="inverse")
        
        # Topix 显示来源
        col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", 
                    delta=f"{tp_pct:+.2%}", delta_color="inverse",
                    help=f"点数: {tp_val:,.2f}\n来源: {tp_src}")
        
        st.divider()
        
        # --- 表格样式 ---
        st.caption("📋 个股表现 (原始涨跌幅)")
        
        # 自定义样式函数：红涨绿跌
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
        
        # 如果是 fallback 数据源，提示一下
        if "Delay" in tp_src:
            st.warning(f"⚠️ 提示：由于网络限制，无法直连 Yahoo Japan，当前 Topix 数据来自 {tp_src} (可能存在 15-20 分钟延迟)。")

    else:
        st.error("没有获取到有效数据，请检查输入。")
