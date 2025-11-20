import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re

# --- 页面配置 ---
st.set_page_config(page_title="日股实盘", page_icon="📱", layout="centered")

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

# --- 核心函数 1：爬取 Google 财经 ---
def get_google_index_data(symbol_code):
    url = f"https://www.google.com/finance/quote/{symbol_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.content, "html.parser")
        
        # 获取现价 (Google Class 名可能会变，YMlKec 目前是主流)
        price_div = soup.find("div", class_="YMlKec fxKbKc")
        if not price_div: return None
        
        current_price = float(price_div.text.replace(",", ""))
        
        # 获取当日涨跌 (尝试从昨收计算)
        prev_close = 0.0
        labels = soup.find_all("div", class_="mfs77b")
        for label in labels:
            if "Previous" in label.text or "昨" in label.text:
                val_div = label.find_next("div", class_="P6K39c")
                if val_div:
                    prev_close = float(val_div.text.replace(",", ""))
                    break
        
        daily_ret = (current_price - prev_close) / prev_close if prev_close > 0 else 0.0
        return {"price": current_price, "daily_ret": daily_ret, "valid": True}
    except:
        return None

# --- 核心函数 2：爬取 Yahoo Japan (备用) ---
def get_yahoo_jp_data(code):
    """爬取 Yahoo Finance Japan (针对 998405.T 等)"""
    url = f"https://finance.yahoo.co.jp/quote/{code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.content, "html.parser")
        
        # Yahoo JP 的价格通常在大字号 span 里，或者通过正则暴力匹配
        # 寻找类似 "2,700.50" 这样的数字结构，且在名为 "price" 或 "number" 的容器附近
        # 这里使用正则粗暴匹配页面中最大的像价格的数字（针对指数通常在 header）
        
        # 尝试方法 A: 找特定 class (Yahoo JP class 经常变，不可靠)
        # 尝试方法 B: 正则匹配 title 或 meta
        # <meta name="description" content="TOPIX【998405.T】の株価... 2,712.34 ...">
        # 但 meta 通常有延迟。
        
        # 尝试方法 C: 找页面里的大数字
        # 提取所有大字文本
        spans = soup.find_all("span")
        candidates = []
        for s in spans:
            text = s.text.strip().replace(',', '')
            # 匹配浮点数
            if re.match(r'^\d{3,5}\.\d{2}$', text):
                candidates.append(float(text))
        
        if not candidates: return None
        
        # 假设页面上方第一个大数字就是现价 (通常指数点位在 2000-40000 之间)
        # 过滤掉不合理的数字
        valid_candidates = [x for x in candidates if x > 500] 
        if not valid_candidates: return None
        
        current_price = valid_candidates[0] # 取第一个匹配到的通常是现价
        
        # 计算涨跌 (简单起见，Yahoo JP 较难爬昨收，这里只返回价格，涨跌设为0或通过其他方式估算)
        # 我们可以用 ETF 的涨跌幅来“借用”给指数
        return {"price": current_price, "daily_ret": 0.0, "valid": True}
        
    except:
        return None

# --- 核心函数 3：yfinance (个股 & 日经) ---
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

        try:
            intraday = stock.history(period="1d", interval="5m")
            if not intraday.empty:
                current_price = intraday['Close'].iloc[-1]
            else:
                current_price = get_safe_price(hist_recent)
        except:
            current_price = get_safe_price(hist_recent)

        daily_ret = 0.0
        if len(hist_recent) >= 2:
            prev_close = hist_recent['Close'].iloc[-2]
            if prev_close > 0:
                daily_ret = (current_price - prev_close) / prev_close

        mtd_ret = 0.0
        buy_price = 0.0
        buy_date = "N/A"
        if not hist_mtd.empty:
            buy_price = hist_mtd.iloc[0]['Open']
            buy_date = hist_mtd.index[0].strftime('%m-%d')
            if buy_price > 0:
                mtd_ret = (current_price - buy_price) / buy_price

        name = ticker_symbol
        if not is_index:
            try:
                info = stock.info
                name = info.get('longName', info.get('shortName', ticker_symbol))
            except:
                pass

        return {
            "name": name, "price": current_price, "daily_ret": daily_ret,
            "mtd_ret": mtd_ret, "buy_price": buy_price, "buy_date": buy_date, "valid": True
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
                "代码": code, "名称": data["name"], "现价": data["price"],
                "买入价": data["buy_price"], "日收益": data["daily_ret"], "月收益": data["mtd_ret"]
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
    
    # 1. 获取数据
    n225 = fetch_market_data("^N225", start_str, is_index=True)
    etf  = fetch_market_data("1306.T", start_str, is_index=True)
    
    # 2. TOPIX 指数获取逻辑 (双保险)
    # Plan A: Google
    topix_data = get_google_index_data("TOPIX:INDEXTOKYO")
    
    # Plan B: Yahoo JP
    if not topix_data:
        # print("Google failed, trying Yahoo JP...")
        yahoo_data = get_yahoo_jp_data("998405.T")
        if yahoo_data:
            topix_data = yahoo_data
            # 如果是从 Yahoo JP 抓的，借用 ETF 的涨跌幅 (因为 Yahoo JP 爬涨跌幅很麻烦)
            if etf["valid"]:
                topix_data["daily_ret"] = etf["daily_ret"]
        else:
            # Plan C: Failed
            topix_data = {"valid": False}

    # 3. 个股
    df = fetch_portfolio_data(clean_codes, start_str)
    
    # --- 界面 ---
    st.caption(f"📊 市场基准 ({now.strftime('%H:%M')})")
    c1, c2, c3 = st.columns(3)
    
    with c1:
        if n225["valid"]:
            st.metric("日经225 (日 | 月)", f"{n225['price']:,.0f}", f"{n225['daily_ret']:+.2%} 日", delta_color="inverse")
            st.caption(f"月: {n225['mtd_ret']:+.1%}")
        else:
            st.metric("日经225", "N/A")
            
    with c2:
        if topix_data and topix_data["valid"]:
            # 借用 ETF 的月涨跌幅，因为爬虫很难爬到历史月线
            mtd_proxy = etf["mtd_ret"] if etf["valid"] else 0.0
            st.metric("TOPIX (日 | 月)", f"{topix_data['price']:,.2f}", f"{topix_data['daily_ret']:+.2%} 日", delta_color="inverse")
            st.caption(f"月: {mtd_proxy:+.1%}")
        else:
            st.metric("TOPIX指数", "暂无数据") # 明确告知失败，不卡在"获取中"

    with c3:
        if etf["valid"]:
            st.metric("ETF 1306 (日 | 月)", f"{etf['price']:,.0f}", f"{etf['daily_ret']:+.2%} 日", delta_color="inverse")
            st.caption(f"月: {etf['mtd_ret']:+.1%}")
        else:
            st.metric("ETF 1306", "N/A")

    st.markdown("---")

    if not df.empty:
        avg_ret = df['月收益'].mean()
        total_ret = avg_ret * leverage
        bench_ret = etf['mtd_ret'] if etf['valid'] else 0
        alpha = total_ret - bench_ret
        
        st.caption("📈 组合表现 (本月累计)")
        sc1, sc2 = st.columns(2)
        with sc1: st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", delta_color="inverse")
        with sc2: st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}", delta_color="off")
             
        st.divider()

        st.subheader(f"持仓详情 ({len(df)}只)")
        df = df.sort_values(by='月收益', ascending=False)
        
        for _, row in df.iterrows():
            c_day = "red" if row['日收益'] > 0 else "green"
            c_mon = "red" if row['月收益'] > 0 else "green"
            with st.container():
                st.markdown(f"**{row['代码']} | {row['名称']}**")
                col1, col2, col3 = st.columns([1.2, 1, 1])
                with col1:
                    st.write(f"¥{row['现价']:,.0f}")
                    st.caption(f"本:¥{row['买入价']:,.0f}")
                with col2:
                    st.markdown(f":{c_day}[{row['日收益']:+.2%}]")
                    st.caption("今日")
                with col3:
                    st.markdown(f":{c_mon}[**{row['月收益']:+.2%}**]")
                    st.caption("本月")
                st.divider()
    else:
        st.error("无法获取数据")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 列表已保存。")

