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

# --- 自定义 HTML 卡片渲染 (核心修改) ---
def display_card(title, main_value_str, sub_info, value_for_color):
    """
    title: 标题 (如 "组合收益")
    main_value_str: 大数字的字符串 (如 "-3.92%")
    sub_info: 下方的小字 (如 "当前: 2800 | 日: +1%")
    value_for_color: 用于判断颜色的数值 (正数红，负数绿)
    """
    # 颜色逻辑: 红涨绿跌
    if value_for_color > 0:
        color = "#d32f2f" # Red
    elif value_for_color < 0:
        color = "#2e7d32" # Green
    else:
        color = "#333333" # Gray/Black

    # HTML 样式
    html_code = f"""
    <div style="
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border: 1px solid #e0e0e0;
    ">
        <div style="font-size: 14px; color: #666; margin-bottom: 5px;">{title}</div>
        <div style="font-size: 32px; font-weight: bold; color: {color}; line-height: 1.2;">
            {main_value_str}
        </div>
        <div style="font-size: 13px; color: #555; margin-top: 8px; font-family: monospace;">
            {sub_info}
        </div>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# --- 爬虫逻辑 (保持 Minkabu) ---
def get_topix_minkabu():
    url = "https://minkabu.jp/stock/KSISU1000"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            price_div = soup.find("div", class_="stock_price")
            if price_div:
                raw_text = price_div.get_text(strip=True)
                clean_text = raw_text.replace('\n', '').replace(' ', '').replace(',', '')
                return float(clean_text)
    except:
        pass
    return None

# --- 核心数据获取 ---
def calculate_data(user_input_str, leverage_ratio):
    month_start = get_month_start_date()
    
    # --- 1. Topix 数据 (包含日涨跌计算) ---
    tp_curr = get_topix_minkabu() # 实时价
    tp_source = "Minkabu"
    tp_prev_close = None # 昨日收盘 (用于算日涨跌)
    tp_month_open = None # 月初开盘 (用于算月涨跌)
    
    # 获取辅助数据 (昨日收盘 & 月初开盘)
    try:
        t = yf.Ticker("^TOPX")
        # 尝试获取昨日收盘
        if t.fast_info.previous_close:
            tp_prev_close = t.fast_info.previous_close
        
        # 如果没爬到实时价，用 yfinance 兜底
        if tp_curr is None:
            if t.fast_info.last_price:
                tp_curr = t.fast_info.last_price
                tp_source = "Yahoo Backup"
            else:
                # 历史数据最后一行
                hist_d = t.history(period="1d")
                if not hist_d.empty:
                    tp_curr = hist_d.iloc[-1]['Close']
                    tp_source = "History Close"

        # 获取月初开盘
        hist_m = t.history(start=month_start, interval="1d")
        if not hist_m.empty:
            tp_month_open = hist_m.iloc[0]['Open']
            # 终极兜底
            if tp_curr is None:
                tp_curr = hist_m.iloc[-1]['Close']
    except:
        pass

    # 计算 Topix 指标
    tp_month_pct = 0.0
    tp_day_pct = 0.0
    
    if tp_curr and tp_month_open:
        tp_month_pct = (tp_curr - tp_month_open) / tp_month_open
    
    if tp_curr and tp_prev_close:
        tp_day_pct = (tp_curr - tp_prev_close) / tp_prev_close
    elif tp_curr and tp_month_open: # 如果取不到昨日收盘，暂用月初代替(虽然不准)或设为0
        pass 

    # --- 2. 日经225 数据 ---
    nk_curr = 0.0
    nk_month_pct = 0.0
    nk_day_pct = 0.0
    try:
        nk = yf.Ticker("^N225")
        nk_fi = nk.fast_info
        nk_curr = nk_fi.last_price
        nk_prev = nk_fi.previous_close
        
        if nk_curr and nk_prev:
            nk_day_pct = (nk_curr - nk_prev) / nk_prev
            
        nk_hist = nk.history(start=month_start, interval="1d")
        if not nk_hist.empty:
            nk_month_open = nk_hist.iloc[0]['Open']
            if nk_curr:
                nk_month_pct = (nk_curr - nk_month_open) / nk_month_open
    except:
        pass

    # --- 3. 个股 & 组合计算 ---
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
        
    alpha = leveraged_port_return - tp_month_pct
    
    return {
        "df": pd.DataFrame(table_rows),
        "port_ret": leveraged_port_return,
        "alpha": alpha,
        "nk": {"pct": nk_month_pct, "val": nk_curr, "day": nk_day_pct},
        "tp": {"pct": tp_month_pct, "val": tp_curr, "day": tp_day_pct, "src": tp_source}
    }

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在从 Minkabu 获取数据...'):
        data = calculate_data(user_input, leverage)
    
    if not data["df"].empty:
        # 使用 st.columns 布局，但内部用自定义 HTML 渲染
        c1, c2, c3, c4 = st.columns(4)
        
        # 1. 组合收益
        with c1:
            display_card(
                title=f"📊 组合月收益 ({leverage}x)",
                main_value_str=f"{data['port_ret']:+.2%}",
                sub_info="基于所有持仓平均涨幅",
                value_for_color=data['port_ret']
            )
            
        # 2. Alpha
        with c2:
            display_card(
                title="🚀 Alpha (vs Topix)",
                main_value_str=f"{data['alpha']:+.2%}",
                sub_info="组合月收益 - Topix月收益",
                value_for_color=data['alpha']
            )
            
        # 3. 日经225 (增加 当前价 | 日涨跌)
        with c3:
            nk_sub = f"当前: {data['nk']['val']:,.0f} | 日: {data['nk']['day']:+.2%}"
            display_card(
                title="🇯🇵 日经225 (月)",
                main_value_str=f"{data['nk']['pct']:+.2%}",
                sub_info=nk_sub,
                value_for_color=data['nk']['pct']
            )
            
        # 4. Topix (增加 当前价 | 日涨跌)
        with c4:
            tp_val = data['tp']['val'] if data['tp']['val'] else 0
            tp_sub = f"当前: {tp_val:,.2f} | 日: {data['tp']['day']:+.2%}"
            display_card(
                title="🇯🇵 Topix (月)",
                main_value_str=f"{data['tp']['pct']:+.2%}",
                sub_info=tp_sub,
                value_for_color=data['tp']['pct']
            )
        
        st.divider()
        
        # 表格 (保持原样，因为表格本来就好看)
        st.caption("📋 个股表现 (原始涨跌幅)")
        def color_arrow(val):
            if val > 0: return 'color: #d32f2f; font-weight: bold'
            elif val < 0: return 'color: #2e7d32; font-weight: bold'
            return 'color: gray'

        styled_df = data["df"].style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(color_arrow, subset=['日涨跌幅', '月涨跌幅'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
    else:
        st.error("无法获取数据。")
