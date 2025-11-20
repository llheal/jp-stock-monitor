import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股策略监控", page_icon="📱")

# --- 1. 智能默认值逻辑 ---
FALLBACK_CODES = "7203, 9984, 8035" 

if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏配置 ---
st.sidebar.header("⚙️ 持仓配置")
user_input = st.sidebar.text_area("持仓代码 (逗号分隔)", value=initial_value, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心数据获取函数 ---

def get_current_price(ticker_symbol):
    """获取最新的实时价格 (兼容盘中和盘后)"""
    try:
        stock = yf.Ticker(ticker_symbol)
        # 尝试获取盘中 5分钟级 数据
        todays_data = stock.history(period="1d", interval="5m")
        if not todays_data.empty:
            return todays_data['Close'].iloc[-1]
        
        # 如果获取不到盘中数据(比如周末)，获取最近日线收盘价
        recent_data = stock.history(period="5d")
        if not recent_data.empty:
            return recent_data['Close'].iloc[-1]
    except:
        pass
    return 0.0

def fetch_index_data(ticker_symbol, start_str):
    """
    获取指数的双重数据：
    1. 当日涨跌 (Daily Return)
    2. 本月涨跌 (MTD Return)
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # A. 获取最近5天日线 (用于计算当日涨跌)
        hist_recent = stock.history(period="5d")
        
        # B. 获取本月历史 (用于计算本月涨跌)
        hist_mtd = stock.history(start=start_str)
        if hist_mtd.empty:
             hist_mtd = stock.history(period="1mo")

        # C. 获取实时价格
        current_price = get_current_price(ticker_symbol)
        if current_price == 0 and not hist_recent.empty:
            current_price = hist_recent['Close'].iloc[-1]

        # --- 计算当日收益 (Daily) ---
        daily_ret = 0.0
        # 昨收价：倒数第2天的收盘价 (如果今天还没收盘，history最后一行可能是今天，也可能是昨天)
        # 这里的逻辑比较 trick，简单起见：
        # 我们假设 hist_recent 的最后一行如果是“今天”，那倒数第二行就是“昨天”
        # yfinance 的 history 在盘中时，最后一行通常是今天的实时数据
        if len(hist_recent) >= 2:
            prev_close = hist_recent['Close'].iloc[-2]
            daily_ret = (current_price - prev_close) / prev_close
        
        # --- 计算本月收益 (MTD) ---
        mtd_ret = 0.0
        if not hist_mtd.empty:
            # 月初开盘价
            month_open = hist_mtd.iloc[0]['Open']
            mtd_ret = (current_price - month_open) / month_open

        return {
            "daily_ret": daily_ret,
            "mtd_ret": mtd_ret,
            "price": current_price,
            "valid": True
        }
    except Exception as e:
        return {"valid": False}

def fetch_stock_data(codes, start_str):
    """获取持仓股票数据 (仅关注本月收益)"""
    data_list = []
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        
        ticker_symbol = f"{code}.T" if not code.endswith(".T") else code
        
        try:
            stock = yf.Ticker(ticker_symbol)
            # 1. 历史数据 (找月初)
            hist = stock.history(start=start_str)
            if hist.empty:
                hist = stock.history(period="1mo")
            
            # 2. 实时价格
            current_price = get_current_price(ticker_symbol)
            if current_price == 0 and not hist.empty:
                current_price = hist['Close'].iloc[-1]
            
            # 3. 月初成本
            buy_price = 0
            buy_date = "N/A"
            if not hist.empty:
                buy_price = hist.iloc[0]['Open']
                buy_date = hist.index[0].strftime('%m-%d')
            
            ret = (current_price - buy_price) / buy_price if buy_price else 0
            
            data_list.append({
                "代码": code,
                "买入日": buy_date,
                "买入价": buy_price,
                "现价": current_price,
                "收益率": ret
            })
        except:
            pass
        
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 主程序逻辑 ---

# 1. 确定时间
jp_tz = pytz.timezone('Asia/Tokyo')
now = datetime.now(jp_tz)
start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
start_str = start_of_month.strftime('%Y-%m-%d')

st.title("📱 日股实盘监控")

# 处理持仓列表
clean_codes_list = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_codes_str = ",".join(clean_codes_list)

if st.button("🔄 刷新行情", type="primary", use_container_width=True):
    # 更新 URL
    st.query_params["codes"] = clean_codes_str
    
    # 1. 获取大盘指数
    # 日经225 (^N225) 和 TOPIX (^TOPX)
    nikkei_data = fetch_index_data("^N225", start_str)
    topix_data = fetch_index_data("^TOPX", start_str)
    
    # 2. 获取个股持仓
    df = fetch_stock_data(clean_codes_list, start_str)
    
    # --- 界面显示部分 ---

    # A. 市场概况卡片
    st.caption(f"📊 市场概况 (东京时间 {now.strftime('%H:%M')})")
    
    # 使用 3 列布局，或者 2 列
    idx_c1, idx_c2 = st.columns(2)
    
    with idx_c1:
        if nikkei_data["valid"]:
            # Value 显示当日涨跌，Delta 显示本月累计
            st.metric(
                label="日经 225 (日 | 月)",
                value=f"{nikkei_data['daily_ret']:+.2%}", 
                delta=f"{nikkei_data['mtd_ret']:+.2%} 本月",
                delta_color="normal" # 红色涨绿色跌(默认逻辑)
            )
        else:
            st.metric("日经 225", "获取失败")
            
    with idx_c2:
        if topix_data["valid"]:
            st.metric(
                label="TOPIX (日 | 月)",
                value=f"{topix_data['daily_ret']:+.2%}", 
                delta=f"{topix_data['mtd_ret']:+.2%} 本月",
                delta_color="normal"
            )
        else:
            st.metric("TOPIX", "获取失败")

    st.markdown("---")

    # B. 策略表现卡片
    if not df.empty:
        avg_ret = df['收益率'].mean()
        total_ret = avg_ret * leverage
        
        # 计算 Alpha (策略本月收益 - TOPIX 本月收益)
        alpha = 0.0
        if topix_data["valid"]:
            alpha = total_ret - topix_data['mtd_ret']

        st.caption("📈 策略表现 (本月累计)")
        strat_c1, strat_c2 = st.columns(2)
        
        with strat_c1:
            st.metric("策略总收益 (杠杆后)", f"{total_ret:+.2%}", 
                      delta_color="normal" if total_ret > 0 else "inverse")
        with strat_c2:
            st.metric("相对 TOPIX (Alpha)", f"{alpha:+.2%}",
                      delta_color="off") # Alpha 不变色，直接看数值

        st.divider()
        
        # C. 个股详情列表
        st.subheader("持仓详情")
        df = df.sort_values(by='收益率', ascending=False)
        
        for _, row in df.iterrows():
            c_code = row['代码']
            c_ret = row['收益率']
            c_price = row['现价']
            
            # 简单配色：涨红跌绿 (如果你习惯美股绿涨红跌，可以反过来)
            color = "red" if c_ret > 0 else "green"
            
            with st.container():
                c1, c2, c3 = st.columns([2, 2, 2])
                c1.markdown(f"**{c_code}**")
                c2.write(f"¥{c_price:,.0f}")
                # 使用 colored text 显示收益率
                c3.markdown(f":{color}[{c_ret:+.2%}]")
                st.divider()
    else:
        if not clean_codes_list:
            st.info("请在侧边栏输入代码")
        else:
            st.error("持仓数据获取失败")

# --- 底部 ---
if "codes" in st.query_params:
    st.caption("💡 提示：列表已保存到网址，请收藏当前页面。")
            stock = yf.Ticker(ticker_symbol)
            # 优先获取历史数据找开盘价
            hist = stock.history(start=start_str, interval="1d")
            
            if hist.empty:
                hist = stock.history(period="1mo", interval="1d")
            
            # 获取实时价 (尝试 5m 数据，因为 info 接口经常慢)
            current_price = 0.0
            # 尝试获取 intraday 数据
            todays_data = stock.history(period="1d", interval="5m")
            
            if not todays_data.empty:
                current_price = todays_data['Close'].iloc[-1]
            elif not hist.empty:
                current_price = hist['Close'].iloc[-1]
            
            # 获取买入价 (月初 Open)
            if not hist.empty:
                buy_price = hist.iloc[0]['Open']
                buy_date = hist.index[0].strftime('%m-%d')
            else:
                buy_price = current_price # 兜底
                buy_date = "N/A"
            
            ret = (current_price - buy_price) / buy_price if buy_price else 0
            
            data_list.append({
                "代码": code,
                "买入日": buy_date,
                "买入价": buy_price,
                "现价": current_price,
                "收益率": ret
            })
            
        except Exception as e:
            pass # 忽略单个错误，继续下一个
        
        progress_bar.progress((i + 1) / len(codes))
    
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 显示界面 ---
st.title("📱 策略实盘监控")

# 处理代码列表
# 清理换行符和空格，压缩成单行字符串，方便存入 URL
clean_codes_list = [c.strip() for c in user_input.replace('\n', ',').replace('，', ',').split(',') if c.strip()]
clean_codes_str = ",".join(clean_codes_list)

# --- 2. 按钮与 URL 更新逻辑 ---
if st.button("🔄 刷新数据 & 保存列表", type="primary", use_container_width=True):
    if not clean_codes_list:
        st.warning("请在侧边栏输入股票代码")
    else:
        # [关键] 将当前输入框的内容，更新到浏览器地址栏
        st.query_params["codes"] = clean_codes_str
        
        # 开始获取数据
        df = get_stock_data(clean_codes_list)
        
        if not df.empty:
            avg_ret = df['收益率'].mean()
            total_ret = avg_ret * leverage
            
            st.metric("组合总收益 (杠杆后)", f"{total_ret:.2%}", 
                      delta_color="normal" if total_ret > 0 else "inverse")
            
            st.markdown("---")
            
            df = df.sort_values(by='收益率', ascending=False)
            
            for _, row in df.iterrows():
                c_code = row['代码']
                c_ret = row['收益率']
                c_price = row['现价']
                
                color = "green" if c_ret > 0 else "red"
                
                with st.container():
                    c1, c2, c3 = st.columns([2, 2, 2])
                    c1.markdown(f"**{c_code}**")
                    c2.write(f"¥{c_price:,.0f}")
                    c3.markdown(f":{color}[{c_ret:+.2%}]")
                    st.divider()
        else:
            st.error("未能获取数据，请检查代码是否正确")

# --- 底部提示 ---
if "codes" in st.query_params:
    st.caption("💡 提示：当前股票列表已保存到网址中。您可以直接**收藏当前网页**，下次打开即为这些股票。")

