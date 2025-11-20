import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面配置 ---
st.set_page_config(page_title="日股策略监控", page_icon="📱")

# --- 1. 智能默认值逻辑 ---
# 这里的代码作为"最后的备选"，如果网址里没有代码，就用这个
FALLBACK_CODES = "7203, 9984, 8035" 

# 从网址栏获取参数 (st.query_params 是 Streamlit 新版API)
# 如果网址是 app.com/?codes=1234,5678，这里就会自动读取出来
if "codes" in st.query_params:
    initial_value = st.query_params["codes"]
else:
    initial_value = FALLBACK_CODES

# --- 侧边栏配置 ---
st.sidebar.header("⚙️ 持仓配置")
# 文本框使用从网址读取到的 initial_value
user_input = st.sidebar.text_area("持仓代码 (逗号分隔)", value=initial_value, height=150)
leverage = st.sidebar.number_input("杠杆率 (x)", value=1.5, step=0.1)

# --- 核心逻辑 (yfinance) ---
def get_stock_data(codes):
    data_list = []
    jp_tz = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jp_tz)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_str = start_of_month.strftime('%Y-%m-%d')
    
    progress_bar = st.progress(0)
    
    for i, code in enumerate(codes):
        code = code.strip()
        if not code: continue
        
        ticker_symbol = f"{code}.T" if not code.endswith(".T") else code
        
        try:
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
