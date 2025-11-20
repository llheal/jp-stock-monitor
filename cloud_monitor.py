import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re

# --- 页面配置 ---
st.set_page_config(page_title="日股实盘全景", page_icon="📱", layout="centered")

# --- 1. 智能默认值 ---
FALLBACK_CODES = "7203, 9984, 8035" 
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏 ---
st.sidebar.header("⚙️ 持仓配置")
user_input = st.sidebar.text_area("持仓代码 (逗号分隔)", value=initial_value, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心函数：爬取 Google 财经 (解决 TOPIX 问题) ---
def get_google_index_data(symbol_code):
    """
    爬取 Google Finance 获取实时指数点位和涨跌
    symbol_code 例如: "TOPIX:INDEXTOKYO" 或 "NI225:INDEXNIKKEI"
    """
    url = f"https://www.google.com/finance/quote/{symbol_code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        r = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(r.content, "html.parser")
        
        # 1. 获取现价 (Google Finance 的大字价格通常在这个 class 里)
        price_div = soup.find("div", class_="YMlKec fxKbKc")
        if not price_div: return {"valid": False}
        
        price_str = price_div.text.replace(",", "")
        current_price = float(price_str)
        
        # 2. 获取当日涨跌幅
        # 涨跌幅通常在价格旁边，带 % 号
        # 我们尝试找包含 % 的 span
        change_divs = soup.find_all("div", class_="JwB6zf") # 这是变化值的容器
        daily_ret = 0.0
        
        # Google 的结构经常变，我们尝试计算：(现价 - 昨收) / 昨收
        # 昨收通常标记为 "Previous close"
        # 遍历所有 P6K39c class (指标数值)，找到昨收
        prev_close = 0.0
        labels = soup.find_all("div", class_="mfs77b") # 标签名 class
        for label in labels:
            if "Previous close" in label.text or "昨" in label.text:
                # 它的值在下一个同级 div 的 P6K39c 里
                val_div = label.find_next("div", class_="P6K39c")
                if val_div:
                    prev_str = val_div.text.replace(",", "")
                    prev_close = float(prev_str)
                    break
        
        if prev_close > 0:
            daily_ret = (current_price - prev_close) / prev_close
        
        # 注意：爬虫很难获取精准的“本月”涨跌，这里暂缺“本月”数据，或者通过 yf 补全
        return {
            "price": current_price,
            "daily_ret": daily_ret,
            "valid": True
        }
    except Exception as e:
        return {"valid": False}

# --- 核心函数：yfinance (个股 & 日经) ---
def get_safe_price(hist_data):
    if not hist_data.empty:
        return hist_data['Close'].iloc[-1]
    return 0.0

def fetch_market_data(ticker_symbol, start_str, is_index=False):
    try:
        stock = yf.Ticker(ticker_symbol)
        hist_recent = stock.history(period="5d")
        hist_mtd = stock.history(start=start_str)
        if hist_mtd.empty: hist_mtd = stock.history(period="1mo")

        # 现价
        try:
            intraday = stock.history(period="1d", interval="5m")
            if not intraday.empty:
                current_price = intraday['Close'].iloc[-1]
            else:
                current_price = get_safe_price(hist_recent)
        except:
            current_price = get_safe_price(hist_recent)

        # 日收益
        daily_ret = 0.0
        if len(hist_recent) >= 2:
            prev_close = hist_recent['Close'].iloc[-2]
            if prev_close > 0:
                daily_ret = (current_price - prev_close) / prev_close

        # 月收益
        mtd_ret = 0.0
        buy_price = 0.0
        buy_date = "N/A"
        if not hist_mtd.empty:
            buy_price = hist_mtd.iloc[0]['Open']
            buy_date = hist_mtd.index[0].strftime('%m-%d')
            if buy_price > 0:
                mtd_ret = (current_price - buy_price) / buy_price

        # 名称
        name = ticker_symbol
        if not is_index:
            try:
                info = stock.info
                name = info.get('longName', info.get('shortName', ticker_symbol))
            except:
                pass

        return {
            "name": name,
            "price": current_price,
            "daily_ret": daily_ret,
            "mtd_ret": mtd_ret,
            "buy_price": buy_price,
            "buy_date": buy_date,
            "valid": True
        }
    except:
        return {"valid": False}

def fetch_portfolio_data(codes, start_str):
    data_list = []
    progress_bar = st.progress(0)
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        ticker = f"{code}.T" if not code.endswith(".T") else code
        data = fetch_market_data(ticker, start_str)
        if data["valid"]:
            data_list.append({
                "代码": code,
                "名称": data["name"],
                "现价": data["price"],
                "买入价": data["buy_price"],
                "日收益": data["daily_ret"],
                "月收益": data["mtd_ret"]
            })
        progress_bar.progress((i + 1) / len(codes))
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主程序 ---

jp_tz = pytz.timezone('Asia/Tokyo')
now = datetime.now(jp_tz)
start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
start_str = start_of_month.strftime('%Y-%m-%d')

st.title("📱 日股实盘全景")

clean_codes = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_str = ",".join(clean_codes)

if st.button("🔄 刷新详细行情", type="primary", use_container_width=True):
    st.query_params["codes"] = clean_str
    
    # --- 1. 获取指数数据 ---
    # A. 日经225 (优先用 yfinance, 数据全)
    n225_yf = fetch_market_data("^N225", start_str, is_index=True)
    
    # B. TOPIX (混合策略)
    # 从 Google Finance 爬取真实点位 (解决 Yahoo 没数据问题)
    topix_google = get_google_index_data("TOPIX:INDEXTOKYO")
    # 从 Yahoo 获取 ETF 数据 (用来计算月度涨跌，因为爬虫很难爬历史数据)
    topix_etf_yf = fetch_market_data("1306.T", start_str, is_index=True)
    
    # --- 2. 获取个股 ---
    df = fetch_portfolio_data(clean_codes, start_str)
    
    # --- 界面：指数概况 ---
    st.caption(f"📊 市场基准 ({now.strftime('%H:%M')})")
    
    c1, c2, c3 = st.columns(3)
    
    # 1. 日经 225
    with c1:
        if n225_yf["valid"]:
            st.metric("日经225", f"{n225_yf['price']:,.0f}", f"{n225_yf['daily_ret']:+.2%} 日", delta_color="inverse")
            st.caption(f"本月: {n225_yf['mtd_ret']:+.2%}") # 另起一行显示月度
        else:
            st.metric("日经225", "N/A")
    
    # 2. TOPIX 指数 (真实点位)
    with c2:
        # 优先使用 Google 爬到的真实点位
        if topix_google["valid"]:
            current_val = topix_google['price']
            daily_ret = topix_google['daily_ret']
        else:
            current_val = 0
            daily_ret = 0
        
        # 月度涨跌幅：借用 ETF 的数据 (因为指数和 ETF 趋势一致)
        mtd_ret_proxy = topix_etf_yf['mtd_ret'] if topix_etf_yf['valid'] else 0.0

        if current_val > 0:
            st.metric("TOPIX指数", f"{current_val:,.2f}", f"{daily_ret:+.2%} 日", delta_color="inverse")
            st.caption(f"本月: {mtd_ret_proxy:+.2%}") # 借用 ETF 的月涨跌
        else:
            st.metric("TOPIX指数", "获取中...") # Google 爬虫偶尔会被挡
            
    # 3. TOPIX ETF (1306)
    with c3:
        if topix_etf_yf["valid"]:
            st.metric("ETF 1306", f"{topix_etf_yf['price']:,.0f}", f"{topix_etf_yf['daily_ret']:+.2%} 日", delta_color="inverse")
            st.caption(f"本月: {topix_etf_yf['mtd_ret']:+.2%}")
        else:
            st.metric("ETF 1306", "N/A")

    st.markdown("---")

    # --- 界面：策略表现 ---
    if not df.empty:
        avg_ret = df['月收益'].mean()
        total_ret = avg_ret * leverage
        
        # Alpha: 策略收益 - TOPIX(ETF)月收益
        bench_ret = topix_etf_yf['mtd_ret'] if topix_etf_yf['valid'] else 0
        alpha = total_ret - bench_ret
        
        st.caption("📈 组合表现 (本月累计)")
        sc1, sc2 = st.columns(2)
        with sc1:
             st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", delta_color="inverse")
        with sc2:
             st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}", delta_color="off")
             
        st.divider()

        # --- 界面：个股列表 ---
        st.subheader(f"持仓详情 ({len(df)}只)")
        df = df.sort_values(by='月收益', ascending=False)
        
        for _, row in df.iterrows():
            name = row['名称']
            code = row['代码']
            price = row['现价']
            cost = row['买入价']
            d_ret = row['日收益']
            m_ret = row['月收益']
            
            c_day = "red" if d_ret > 0 else "green"
            c_mon = "red" if m_ret > 0 else "green"
            
            with st.container():
                st.markdown(f"**{code} | {name}**")
                col1, col2, col3 = st.columns([1.2, 1, 1])
                with col1:
                    st.write(f"¥{price:,.0f}")
                    st.caption(f"本:¥{cost:,.0f}")
                with col2:
                    st.markdown(f":{c_day}[{d_ret:+.2%}]")
                    st.caption("今日")
                with col3:
                    st.markdown(f":{c_mon}[**{m_ret:+.2%}**]")
                    st.caption("本月")
                st.divider()
    else:
        st.error("无法获取数据")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 列表已保存。")
