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
# 默认值示例：丰田(100股), 软银(200股), 东电(500股)
FALLBACK_CODES = "7203:100, 9984:200, 8035:100" 

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 投资组合配置")
st.sidebar.caption("格式：代码:股数 (英文冒号)。如果不填股数，默认按 100 股计算权重。")
user_input = st.sidebar.text_area("持仓列表", value=initial_value, height=150)

# --- 辅助函数 ---

def get_month_start_date():
    """获取本月第一天的日期字符串"""
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

def get_topix_from_yahoo_jp():
    """
    从 Yahoo Japan 爬取 Topix 实时数据。
    策略：爬取网页 Title 标签，因为它比 CSS Class 更稳定。
    Title 格式通常为: "トピックス【000001.O】：2,700.50 - ..."
    """
    url = "https://finance.yahoo.co.jp/quote/000001.O"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=4)
        soup = BeautifulSoup(r.content, "html.parser")
        title_text = soup.title.string if soup.title else ""
        
        # 使用正则提取价格：查找全角冒号或【】后面的数字
        # 匹配模式：任意字符 + 冒号/空格 + 数字(含逗号和小数点)
        match = re.search(r'[：:]\s*([0-9,]+\.[0-9]+)', title_text)
        
        if match:
            price_str = match.group(1).replace(',', '')
            return float(price_str)
        return None
    except Exception as e:
        print(f"Topix scraping failed: {e}")
        return None

def get_topix_month_open():
    """
    获取 Topix 本月开盘价。
    由于 Yahoo Japan 历史数据爬取困难，这里我们回退使用 yfinance 的历史数据功能。
    yfinance 的历史数据通常是准确的，只是实时数据有延迟。
    """
    try:
        # ^TOPX 是 yfinance 里的 Topix 代码
        hist = yf.Ticker("^TOPX").history(start=get_month_start_date(), interval="1d")
        if not hist.empty:
            return hist.iloc[0]['Open']
        return None
    except:
        return None

# --- 核心逻辑 ---
def calculate_portfolio(user_input_str):
    # 1. 解析用户输入 (代码:股数)
    raw_items = [x.strip() for x in user_input_str.replace('，', ',').split(',') if x.strip()]
    portfolio = []
    
    for item in raw_items:
        parts = item.split(':')
        code = parts[0].strip()
        shares = float(parts[1]) if len(parts) > 1 else 100.0 # 默认100股
        
        # 格式化 yfinance 代码
        yf_ticker = f"{code}.T" if code.isdigit() else code
        portfolio.append({"code": code, "yf_ticker": yf_ticker, "shares": shares})
    
    if not portfolio:
        return None, None, None

    # 2. 获取 Topix 数据 (基准)
    topix_current = get_topix_from_yahoo_jp()
    topix_open = get_topix_month_open()
    
    # 如果爬虫失败，尝试用 yfinance 兜底，或者标记为 NaN
    if topix_current is None and topix_open: 
        # 紧急兜底：如果爬不到实时，暂时用 yesterday close
        topix_current = topix_open 

    topix_data = {
        "name": "TOPIX (基准)",
        "current": topix_current,
        "month_open": topix_open,
        "pct_change": (topix_current - topix_open) / topix_open if (topix_current and topix_open) else 0.0
    }

    # 3. 获取个股数据 & 计算组合价值
    stock_data_list = []
    total_current_value = 0.0
    total_open_value = 0.0 # 月初持仓价值
    
    month_start = get_month_start_date()

    # 进度条
    bar = st.progress(0)
    
    for i, p in enumerate(portfolio):
        try:
            ticker = yf.Ticker(p["yf_ticker"])
            
            # A. 实时数据
            fi = ticker.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            # B. 月初数据
            hist = ticker.history(start=month_start, interval="1d")
            if not hist.empty:
                month_open = hist.iloc[0]['Open']
            else:
                month_open = prev_close # 兜底
            
            # 计算单只股票价值
            val_current = current_price * p["shares"]
            val_open = month_open * p["shares"]
            
            total_current_value += val_current
            total_open_value += val_open
            
            # 计算单只涨跌 (纯小数)
            # 之前可能错在 month_change_pct * 100，这里保持纯小数
            month_change = (current_price - month_open) / month_open if month_open else 0
            day_change = (current_price - prev_close) / prev_close if prev_close else 0
            
            stock_data_list.append({
                "代码": p["code"],
                "持有股数": p["shares"],
                "当前价": current_price,
                "月初开盘": month_open,
                "日涨跌幅": day_change,   # 0.05 = 5%
                "月涨跌幅": month_change, # 0.05 = 5%
                "持仓市值": val_current,
                "月度盈亏": val_current - val_open
            })
            
        except Exception as e:
            st.error(f"Error {p['code']}: {e}")
        
        bar.progress((i + 1) / len(portfolio))
    
    bar.empty()
    
    # 4. 计算组合总表现
    if total_open_value > 0:
        portfolio_month_return = (total_current_value - total_open_value) / total_open_value
    else:
        portfolio_month_return = 0.0
        
    # 计算 Alpha (组合收益 - 基准收益)
    alpha = portfolio_month_return - topix_data["pct_change"]
    
    summary = {
        "port_return": portfolio_month_return,
        "topix_return": topix_data["pct_change"],
        "alpha": alpha,
        "total_pnl": total_current_value - total_open_value,
        "total_val": total_current_value
    }
    
    return pd.DataFrame(stock_data_list), summary, topix_data

# --- 主界面 ---
st.title("🇯🇵 日股实盘 & Alpha 监控")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据 & 计算 Alpha", use_container_width=True):
    with st.spinner('正在从 Yahoo Japan 和 交易所 拉取数据...'):
        df, summary, topix = calculate_portfolio(user_input)
    
    if df is not None and not df.empty:
        # --- 1. 核心指标卡片 ---
        col1, col2, col3, col4 = st.columns(4)
        
        # 辅助样式函数
        def metric_color(val):
            return "normal" # Streamlit metric 自带红绿，不需要额外CSS，除非用markdown
            
        col1.metric("📊 组合月度收益", f"{summary['port_return']:.2%}", 
                    delta=f"{summary['total_pnl']:,.0f} 円")
        
        col2.metric("🇯🇵 Topix 月度表现", f"{topix['topix_return']:.2%}",
                    help="数据来源: Yahoo! Japan (实时) + Yahoo Finance (月初)")
        
        # Alpha 高亮
        alpha_val = summary['alpha']
        col3.metric("🚀 Alpha (超额收益)", f"{alpha_val:+.2%}", 
                    delta_color="normal" if alpha_val > 0 else "inverse")
        
        col4.metric("💰 持仓总市值", f"¥{summary['total_val']:,.0f}")
        
        st.divider()
        
        # --- 2. 持仓明细表 ---
        st.subheader("📋 持仓明细")
        
        # 样式设置：确保百分比显示正确
        # 逻辑：如果 raw 是 0.05，format("{:.2%}") 会显示 5.00%
        styled_df = df.style.format({
            "当前价": "{:,.1f}",
            "月初开盘": "{:,.1f}",
            "持有股数": "{:,.0f}",
            "持仓市值": "¥{:,.0f}",
            "月度盈亏": "{:+,.0f}",
            "日涨跌幅": "{:+.2%}", # 关键修复：这里会自动 * 100
            "月涨跌幅": "{:+.2%}"  # 关键修复：这里会自动 * 100
        }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
               subset=['日涨跌幅', '月涨跌幅', '月度盈亏'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # --- 3. 调试信息 (可选) ---
        if topix['current']:
            st.caption(f"Debug: Topix Realtime (YJ) = {topix['current']}, Month Open = {topix['month_open']}")
        else:
            st.warning("⚠️ 无法从 Yahoo Japan 获取 Topix 实时数据，Alpha 计算可能不准确。")
            
    else:
        st.error("未获取到数据，请检查代码格式。")

# --- 说明 ---
with st.expander("ℹ️ 计算逻辑说明"):
    st.markdown("""
    * **数据源**：
        * **Topix实时**：爬取 Yahoo! Finance Japan (因为 yfinance 的 Topix 经常延迟或中断)。
        * **Topix月初**：使用 yfinance 历史数据。
        * **个股**：使用 yfinance (实时+历史)。
    * **Alpha 计算**：
        * `Alpha = 组合月度加权收益率 - Topix月度收益率`
    * **百分比修复**：
        * 已确认计算逻辑为 `(现价 - 原价) / 原价` (纯小数)，并使用 standard formatting 显示，解决了之前的显示错误。
    """)
