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
FALLBACK_CODES = "7203:100, 9984:200, 8035:100" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")
st.sidebar.caption("格式：代码:股数。默认 100 股。")
user_input = st.sidebar.text_area("持仓列表", value=initial_value, height=150)

# --- 辅助函数 ---
def get_month_start_date():
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

def get_topix_from_yahoo_jp():
    """从 Yahoo Japan 爬取 Topix 实时数据 (爬取 Title 标签)"""
    url = "https://finance.yahoo.co.jp/quote/000001.O"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(r.content, "html.parser")
        title_text = soup.title.string if soup.title else ""
        match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', title_text)
        if match:
            return float(match.group(1).replace(',', ''))
        return None
    except Exception:
        return None

def get_topix_month_open():
    """获取 Topix 本月开盘价 (yfinance)"""
    try:
        hist = yf.Ticker("^TOPX").history(start=get_month_start_date(), interval="1d")
        if not hist.empty:
            return hist.iloc[0]['Open']
        return None
    except:
        return None

# --- 核心逻辑 ---
def calculate_portfolio(user_input_str):
    # 1. 解析用户输入
    raw_items = [x.strip() for x in user_input_str.replace('，', ',').split(',') if x.strip()]
    portfolio = []
    for item in raw_items:
        parts = item.split(':')
        code = parts[0].strip()
        shares = float(parts[1]) if len(parts) > 1 else 100.0
        yf_ticker = f"{code}.T" if code.isdigit() else code
        portfolio.append({"code": code, "yf_ticker": yf_ticker, "shares": shares})
    
    if not portfolio:
        return None, None, None

    # 2. 获取 Topix 数据
    topix_current = get_topix_from_yahoo_jp()
    topix_open = get_topix_month_open()
    
    # 兜底逻辑
    if topix_current is None and topix_open: 
        topix_current = topix_open 

    # 计算 Topix 涨跌
    if topix_current and topix_open:
        topix_ret = (topix_current - topix_open) / topix_open
    else:
        topix_ret = 0.0

    topix_data = {
        "current": topix_current,
        "month_open": topix_open,
        "topix_return": topix_ret  # <--- 修复点：键名保持一致
    }

    # 3. 计算个股与组合
    stock_data_list = []
    total_current_value = 0.0
    total_open_value = 0.0
    month_start = get_month_start_date()
    
    bar = st.progress(0)
    
    for i, p in enumerate(portfolio):
        try:
            ticker = yf.Ticker(p["yf_ticker"])
            fi = ticker.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            hist = ticker.history(start=month_start, interval="1d")
            month_open = hist.iloc[0]['Open'] if not hist.empty else prev_close
            
            val_current = current_price * p["shares"]
            val_open = month_open * p["shares"]
            total_current_value += val_current
            total_open_value += val_open
            
            month_change = (current_price - month_open) / month_open if month_open else 0
            day_change = (current_price - prev_close) / prev_close if prev_close else 0
            
            stock_data_list.append({
                "代码": p["code"],
                "持有股数": p["shares"],
                "当前价": current_price,
                "月初开盘": month_open,
                "日涨跌幅": day_change,
                "月涨跌幅": month_change,
                "持仓市值": val_current,
                "月度盈亏": val_current - val_open
            })
        except Exception as e:
            print(f"Error {p['code']}: {e}")
        
        bar.progress((i + 1) / len(portfolio))
    
    bar.empty()
    
    # 4. 汇总计算
    if total_open_value > 0:
        portfolio_month_return = (total_current_value - total_open_value) / total_open_value
    else:
        portfolio_month_return = 0.0
        
    alpha = portfolio_month_return - topix_data["topix_return"]
    
    summary = {
        "port_return": portfolio_month_return,
        "alpha": alpha,
        "total_pnl": total_current_value - total_open_value,
        "total_val": total_current_value
    }
    
    return pd.DataFrame(stock_data_list), summary, topix_data

# --- 主界面 ---
st.title("🇯🇵 日股实盘 & Alpha 监控")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算数据...'):
        df, summary, topix = calculate_portfolio(user_input)
    
    if df is not None and not df.empty:
        # 1. 指标卡片
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("📊 组合月度收益", f"{summary['port_return']:.2%}", 
                    delta=f"{summary['total_pnl']:,.0f} 円")
        
        # 修复点：现在这里的键名 topix_return 可以在字典里找到了
        col2.metric("🇯🇵 Topix 月度表现", f"{topix['topix_return']:.2%}")
        
        alpha_val = summary['alpha']
        col3.metric("🚀 Alpha (超额收益)", f"{alpha_val:+.2%}", 
                    delta_color="normal" if alpha_val > 0 else "inverse")
        
        col4.metric("💰 持仓总市值", f"¥{summary['total_val']:,.0f}")
        
        st.divider()
        
        # 2. 表格展示
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "月初开盘": "{:,.1f}",
            "持有股数": "{:,.0f}",
            "持仓市值": "¥{:,.0f}",
            "月度盈亏": "{:+,.0f}",
            "日涨跌幅": "{:+.2%}",
            "月涨跌幅": "{:+.2%}"
        }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
               subset=['日涨跌幅', '月涨跌幅', '月度盈亏'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        if topix['current'] is None:
             st.warning("注意：未能获取 Topix 实时数据，Alpha 暂基于今日开盘或昨日收盘计算。")
            
    else:
        st.error("获取数据失败或代码格式错误。")
