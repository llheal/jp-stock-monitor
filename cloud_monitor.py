import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股深度看板", page_icon="🇯🇵", layout="centered")

# --- 1. 配置区域 ---
FALLBACK_CODES = "7203, 9984, 8035" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

st.sidebar.header("⚙️ 监控配置")
user_input = st.sidebar.text_area("持仓/关注代码 (逗号分隔)", value=initial_value, height=100)
st.sidebar.caption("系统会自动添加 日经225 和 TOPIX 指数。")

# --- 辅助函数：获取本月第一天日期 ---
def get_month_start_date():
    #以此确保请求历史数据时覆盖到本月第一天
    tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(tz)
    return now.replace(day=1).strftime('%Y-%m-%d')

# --- 核心函数：获取数据 ---
def get_market_data(user_codes_str):
    # 1. 定义指数列表
    indices = [
        {"code": "^N225", "name": "日经225", "type": "指数"},
        {"code": "^TOPX", "name": "TOPIX", "type": "指数"}
    ]
    
    # 2. 处理用户输入的个股
    raw_codes = [c.strip() for c in user_codes_str.replace('，', ',').split(',') if c.strip()]
    stock_tickers = []
    for code in raw_codes:
        # 如果是纯数字，加 .T；如果带后缀或指数代码则保留
        if code.isdigit():
            stock_tickers.append({"code": f"{code}.T", "name": code, "type": "个股"})
        else:
            stock_tickers.append({"code": code, "name": code, "type": "个股"})
    
    # 合并列表：指数在前，个股在后
    all_items = indices + stock_tickers
    
    data_list = []
    month_start = get_month_start_date()
    
    # 进度条
    progress_bar = st.progress(0)
    
    for i, item in enumerate(all_items):
        ticker_symbol = item["code"]
        try:
            stock = yf.Ticker(ticker_symbol)
            
            # --- A. 获取实时/今日数据 ---
            fi = stock.fast_info
            current_price = fi.last_price
            prev_close = fi.previous_close
            
            # 日涨跌计算
            if prev_close and prev_close > 0:
                day_change_pct = ((current_price - prev_close) / prev_close)
                day_change_amt = current_price - prev_close
            else:
                day_change_pct = 0
                day_change_amt = 0

            # --- B. 获取月度数据 (计算月涨跌) ---
            # 获取从本月1号开始的历史数据
            hist = stock.history(start=month_start, interval="1d")
            
            if not hist.empty:
                # 逻辑：取 hist 的第一行（即本月第一个交易日）的 'Open' 价
                month_open_price = hist.iloc[0]['Open']
                
                if month_open_price > 0:
                    month_change_pct = (current_price - month_open_price) / month_open_price
                else:
                    month_change_pct = 0
            else:
                month_open_price = current_price # 兜底
                month_change_pct = 0

            data_list.append({
                "名称/代码": item["name"],
                "类型": item["type"],
                "当前价": current_price,
                "日涨跌幅": day_change_pct, # 保持小数，后面用format格式化
                "日涨跌额": day_change_amt,
                "月涨跌幅": month_change_pct,
                "月初开盘": month_open_price
            })
            
        except Exception as e:
            pass # 忽略获取失败的个股
            
        progress_bar.progress((i + 1) / len(all_items))
        
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主界面 ---
st.title("🇯🇵 日股深度行情")
st.caption(f"刷新时间 (JST): {datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%H:%M:%S')}")

if st.button("🔄 刷新数据", use_container_width=True):
    with st.spinner('正在计算日线与月线数据...'):
        df = get_market_data(user_input)
    
    if not df.empty:
        # --- 样式定义 ---
        def style_dataframe(dataframe):
            return dataframe.style.format({
                "当前价": "{:,.1f}",
                "月初开盘": "{:,.1f}",
                "日涨跌额": "{:+.1f}",
                "日涨跌幅": "{:+.2%}",
                "月涨跌幅": "{:+.2%}"
            }).map(lambda x: 'color: #d32f2f; font-weight: bold' if x > 0 else ('color: #2e7d32; font-weight: bold' if x < 0 else 'color: gray'), 
                   subset=['日涨跌幅', '日涨跌额', '月涨跌幅'])

        # 分开展示指数和个股，或者合并展示
        # 这里为了直观，我们把指数高亮或者置顶
        
        st.subheader("📊 市场概览 & 持仓")
        st.dataframe(
            style_dataframe(df), 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "类型": st.column_config.TextColumn("类型", width="small"),
                "月涨跌幅": st.column_config.ProgressColumn(
                    "月度表现",
                    format="%.2f%%",
                    min_value=-0.2, # 进度条范围 -20% 到 +20%
                    max_value=0.2,
                ),
            }
        )
        
        # 简单的文字总结
        nikkei = df[df['名称/代码'] == '日经225']
        if not nikkei.empty:
            nk_val = nikkei.iloc[0]['日涨跌幅']
            st.info(f"日经225 今日表现: {nk_val:+.2%}")

    else:
        st.error("获取数据失败，请检查网络或代码。")

# --- 说明区域 ---
with st.expander("ℹ️ 涨跌幅计算说明"):
    st.markdown("""
    * **日涨跌幅**：`(当前价 - 昨日收盘价) / 昨日收盘价`
    * **月涨跌幅**：`(当前价 - 本月首个交易日开盘价) / 本月首个交易日开盘价`
    * **数据源**：Yahoo Finance (延迟约 15-20 分钟，指数数据可能视API情况而定)
    """)
