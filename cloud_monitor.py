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

# --- 核心爬虫：Minkabu (暴力正则版) ---
def get_topix_minkabu_regex():
    """
    直接在 HTML 源码中搜索特定模式，无视 DOM 结构
    Pattern: 数字(可能含逗号) + . + <span class="decimal"> + 数字 + </span>
    """
    url = "https://minkabu.jp/stock/KSISU1000"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            # 1. 针对你提供的 HTML 结构进行正则匹配
            # 目标: 3,289.<span class="decimal">64</span>
            # \s* 处理可能存在的空格或换行
            pattern = r'([0-9,]+)\.\s*<span\s+class="decimal">([0-9]+)</span>'
            
            match = re.search(pattern, r.text)
            if match:
                # 提取整数部分 (3,289) 和 小数部分 (64)
                integer_part = match.group(1).replace(',', '')
                decimal_part = match.group(2)
                full_price = float(f"{integer_part}.{decimal_part}")
                return full_price
                
            # 2. 备用正则：也许有些时候没有 decimal span，直接找 stock_price div 里的纯文本
            soup = BeautifulSoup(r.content, "html.parser")
            price_div = soup.find("div", class_="stock_price")
            if price_div:
                text = price_div.get_text(strip=True) # 会变成 3,289.64
                # 移除非数字字符（保留小数点）
                clean_price = re.sub(r'[^\d.]', '', text)
                return float(clean_price)

    except Exception as e:
        print(f"Minkabu Regex Error: {e}")
        return None
    return None

# --- 综合数据获取 (含 ETF 救生圈) ---
def get_topix_data_robust(month_start):
    price = None
    source = "Init"
    
    # 1. 优先尝试 Minkabu (暴力正则)
    price = get_topix_minkabu_regex()
    if price:
        source = "Minkabu (Live)"
    
    # 2. 失败则尝试 yfinance ^TOPX (容灾)
    if price is None:
        try:
            t = yf.Ticker("^TOPX")
            if t.fast_info.last_price:
                price = t.fast_info.last_price
                source = "Yahoo Finance (^TOPX)"
        except:
            pass

    # 3. 【救生圈】如果以上全挂，使用 ETF (1306.T)
    # 这是野村 TOPIX ETF，绝对能取到数据，涨跌幅与指数基本一致
    use_etf_proxy = False
    if price is None:
        try:
            etf = yf.Ticker("1306.T")
            if etf.fast_info.last_price:
                price = etf.fast_info.last_price
                source = "ETF Proxy (1306.T)"
                use_etf_proxy = True
        except:
            pass

    # 4. 获取月初基准
    # 如果用了 ETF，基准也要用 ETF 的历史数据
    target_symbol = "1306.T" if use_etf_proxy else "^TOPX"
    month_open = None
    
    try:
        hist = yf.Ticker(target_symbol).history(start=month_start, interval="1d")
        if not hist.empty:
            month_open = hist.iloc[0]['Open']
            # 终极兜底：如果当前价还是 None，用历史收盘价
            if price is None:
                price = hist.iloc[-1]['Close']
                source = f"History Close ({target_symbol})"
    except:
        pass
        
    return price, month_open, source

# --- 核心计算逻辑 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # 1. Topix
    tp_curr, tp_open, tp_src = get_topix_data_robust(month_start)
    
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
    with st.spinner('正在获取数据 (正则匹配模式)...'):
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
        
        # Topix 显示逻辑
        if tp_val > 0:
            tp_help = f"点数: {tp_val:,.2f}\n来源: {tp_src}"
            if "ETF Proxy" in tp_src:
                tp_help += "\n⚠️ 注意：网站反爬严重，当前使用 1306.T (ETF) 近似计算涨跌。"
            
            col4.metric("🇯🇵 Topix (月)", f"{tp_pct:+.2%}", 
                        delta=f"{tp_pct:+.2%}", delta_color="inverse",
                        help=tp_help)
        else:
            col4.metric("🇯🇵 Topix (月)", "N/A", help=f"获取失败，来源: {tp_src}")
        
        st.divider()
        
        # 表格
        st.caption("📋 个股表现 (原始涨跌幅)")
        
        def color_arrow(val):
            if val > 0:
                return 'color: #d32f2f; font-weight: bold' 
            elif val < 0:
                return 'color: #2e7d32; font-weight: bold' 
            return 'color: gray'

        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(color_arrow, subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        st.caption(f"Topix 数据源: {tp_src}")
        
    else:
        st.error("无法获取数据。")
