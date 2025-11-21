import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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

# --- 自定义 HTML 卡片渲染 ---
def display_card(title, main_value_str, sub_info, value_for_color):
    """
    自定义卡片组件：大数字直接变色，无边框
    """
    # 颜色逻辑: 红涨绿跌
    if value_for_color > 0:
        color = "#d32f2f" # Red
    elif value_for_color < 0:
        color = "#2e7d32" # Green
    else:
        color = "#333333" # Gray/Black

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

# --- 爬虫逻辑 (Minkabu - 仅获取当前点数) ---
def get_topix_value_minkabu():
    url = "https://minkabu.jp/stock/KSISU1000"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, headers=headers, timeout=3)
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
    # 获取本月第一天用于计算月收益
    month_start_str = get_month_start_date() 
    
    # ==========================================
    # 1. Topix 混合逻辑 (Value: Minkabu, %: ETF)
    # ==========================================
    
    # A. 获取点数 (面子)
    tp_val = get_topix_value_minkabu()
    if tp_val is None:
        tp_val = 0.0
    
    # B. 获取涨跌幅 (里子 - 使用 1306.T)
    tp_month_pct = 0.0
    tp_day_pct = 0.0
    
    try:
        etf = yf.Ticker("1306.T")
        fi = etf.fast_info
        etf_curr = fi.last_price
        etf_prev = fi.previous_close
        
        if etf_curr and etf_prev:
            tp_day_pct = (etf_curr - etf_prev) / etf_prev
            
        # 获取过去2个月数据以确保覆盖月初
        hist = etf.history(period="2mo", interval="1d")
        
        if not hist.empty:
            # 筛选出本月的数据
            curr_month_data = hist[hist.index.strftime('%Y-%m-%d') >= month_start_str]
            if not curr_month_data.empty:
                etf_month_open = curr_month_data.iloc[0]['Open']
                if etf_curr:
                    tp_month_pct = (etf_curr - etf_month_open) / etf_month_open
    except:
        pass

    # ==========================================
    # 2. 日经225 数据 (正常 yfinance)
    # ==========================================
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
            
        nk_hist = nk.history(period="2mo", interval="1d")
        if not nk_hist.empty:
            curr_month_nk = nk_hist[nk_hist.index.strftime('%Y-%m-%d') >= month_start_str]
            if not curr_month_nk.empty:
                nk_month_open = curr_month_nk.iloc[0]['Open']
                if nk_curr:
                    nk_month_pct = (nk_curr - nk_month_open) / nk_month_open
    except:
        pass

    # ==========================================
    # 3. 个股 & 组合计算
    # ==========================================
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
            
            # 获取2个月数据，既能覆盖本月，也能覆盖过去30天
            hist = stock.history(period="2mo", interval="1d")
            
            day_change = 0.0
            month_change = 0.0
            avg_turnover_30d = 0.0
            
            if not hist.empty and current_price:
                # --- 1. 计算月涨跌幅 ---
                curr_month_hist = hist[hist.index.strftime('%Y-%m-%d') >= month_start_str]
                
                if not curr_month_hist.empty:
                    month_open = curr_month_hist.iloc[0]['Open']
                else:
                    month_open = hist.iloc[0]['Open']
                
                day_change = (current_price - prev_close) / prev_close if prev_close else 0
                month_change = (current_price - month_open) / month_open if month_open else 0
                
                # --- 2. 计算近30天平均成交额 ---
                # 计算每日成交额
                hist['Turnover'] = hist['Close'] * hist['Volume']
                
                # 确定30天前的截止日期
                last_date = hist.index.max()
                cutoff_date = last_date - timedelta(days=30)
                
                # 筛选最近30天的数据
                recent_30d_mask = hist.index > cutoff_date
                if recent_30d_mask.any():
                    # 计算平均值并转换为 亿
                    avg_turnover_raw = hist.loc[recent_30d_mask, 'Turnover'].mean()
                    avg_turnover_30d = avg_turnover_raw / 100_000_000 # 1亿 = 10^8
                
            individual_returns.append(month_change)
            
            table_rows.append({
                "代码": code,
                "当前价": current_price,
                "日涨跌幅": day_change,
                "月涨跌幅": month_change,
                "30日均额(亿)": avg_turnover_30d
            })
        except Exception as e:
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
    
    # 创建并排序 DataFrame
    df = pd.DataFrame(table_rows)
    if not df.empty:
        df = df.sort_values(by='月涨跌幅', ascending=False)

    return {
        "df": df,
        "port_ret": leveraged_port_return,
        "alpha": alpha,
        "nk": {"pct": nk_month_pct, "val": nk_curr, "day": nk_day_pct},
        "tp": {"pct": tp_month_pct, "val": tp_val, "day": tp_day_pct}
    }

# --- 主界面 ---
st.title("🇯🇵 日股收益率看板")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算 (Topix: Minkabu点数 + 1306.T涨跌)...'):
        data = calculate_data(user_input, leverage)
    
    if not data["df"].empty:
        c1, c2, c3, c4 = st.columns(4)
        
        # 1. 组合收益
        with c1:
            display_card(
                title=f"📊 组合月收益 ({leverage}x)",
                main_value_str=f"{data['port_ret']:+.2%}",
                sub_info="基于持仓平均涨幅",
                value_for_color=data['port_ret']
            )
            
        # 2. Alpha
        with c2:
            display_card(
                title="🚀 Alpha (vs Topix)",
                main_value_str=f"{data['alpha']:+.2%}",
                sub_info="超额收益 (月度)",
                value_for_color=data['alpha']
            )
            
        # 3. 日经225
        with c3:
            nk_sub = f"当前: {data['nk']['val']:,.0f} | 日: {data['nk']['day']:+.2%}"
            display_card(
                title="🇯🇵 日经225 (月)",
                main_value_str=f"{data['nk']['pct']:+.2%}",
                sub_info=nk_sub,
                value_for_color=data['nk']['pct']
            )
            
        # 4. Topix
        with c4:
            tp_val_str = f"{data['tp']['val']:,.2f}" if data['tp']['val'] > 0 else "N/A"
            tp_sub = f"当前: {tp_val_str} | 日(ETF): {data['tp']['day']:+.2%}"
            
            display_card(
                title="🇯🇵 Topix (月)",
                main_value_str=f"{data['tp']['pct']:+.2%}",
                sub_info=tp_sub,
                value_for_color=data['tp']['pct']
            )
        
        st.divider()
        
        # 表格
        st.caption("📋 个股表现 (月涨幅排序)")
        def color_arrow(val):
            if val > 0: return 'color: #d32f2f; font-weight: bold'
            elif val < 0: return 'color: #2e7d32; font-weight: bold'
            return 'color: gray'

        # 格式化：成交额保留两位小数
        styled_df = data["df"].style.format({
            "当前价": "{:,.1f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}",
            "30日均额(亿)": "{:,.2f}"
        }).map(color_arrow, subset=['日涨跌幅', '月涨跌幅'])
        
        # 动态高度
        calc_height = (len(data["df"]) + 1) * 35 + 3
        
        st.dataframe(
            styled_df, 
            use_container_width=True, 
            hide_index=True,
            height=calc_height 
        )
        
    else:
        st.error("无法获取数据。")
