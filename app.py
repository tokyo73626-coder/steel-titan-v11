import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import io, requests, socket, urllib3
from datetime import datetime
from pipeline import get_titan_data
from opp import TitanOpp

# 禁用不安全請求警告（因為我們會使用 verify=False）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- [關鍵修正] 增加 verify=False 以跳過雲端環境對證交所的 SSL 檢查 ---
@st.cache_data(ttl=86400)
def get_all_taiwan_symbols():
    url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"

    def fetch_codes(url, suffix):
        out = []
        try:
            # 在這裡加入 verify=False，解決雲端主機不認得證交所憑證的問題
            r = requests.get(url, timeout=15, verify=False)
            r.encoding = 'cp950'
            df = pd.read_html(io.StringIO(r.text))[0]
            df.columns = df.iloc[0]
            codes = df.iloc[1:]['有價證券代號及名稱'].astype(str).str.split('　').str[0]
            for c in codes:
                if c.isdigit() and len(c) == 4:
                    out.append(f"{c}.{suffix}")
        except Exception as e:
            st.warning(f"⚠️ 抓取 {suffix} 名單失敗：{e}")
        return out

    stocks = fetch_codes(url_twse, "TW") + fetch_codes(url_tpex, "TWO")
    return sorted(list(set(stocks)))

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

# --- 網頁配置 ---
st.set_page_config(page_title="鋼鐵泰坦 v11.9 PRO", layout="wide")
st.title("🛡️ 鋼鐵泰坦 v11.9：核心戰情終端")

# 初始化停止旗標
if "stop_scan" not in st.session_state:
    st.session_state.stop_scan = False

# 基礎監控池
target_symbols = ["2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW", "1513.TW", "1519.TW", "1605.TW", "2618.TW", "2308.TW", "2376.TW", "2449.TW", "3034.TW", "3037.TW", "1503.TW", "3711.TW"]

@st.cache_data(ttl=3600)
def load_market_status(symbol_pool):
    today_str = datetime.now().strftime('%Y-%m-%d')
    idx, all_data, rs_thresholds = get_titan_data(symbol_pool, "0050.TW", "2025-01-01", today_str)
    
    need = ['Close','MA50','MA50_Slope','Breadth','Breadth_MA5']
    valid_mask = idx[need].notna().all(axis=1)
    
    if not valid_mask.any():
        return idx, all_data, rs_thresholds, None
    
    last_valid_date = idx.index[valid_mask][-1]
    return idx, all_data, rs_thresholds, last_valid_date

with st.spinner('📡 正在同步 2026 最新戰報...'):
    idx, all_data, rs_thresholds, last_date = load_market_status(target_symbols)

if last_date is None:
    st.error("❌ 無法取得有效交易資料")
    st.stop()

idx_today = idx.loc[last_date]
shield_on = (idx_today['Close'] > idx_today['MA50']) and bool(idx_today['MA50_Slope'])

st.sidebar.header("📡 任務控制中心")
scan_mode = st.sidebar.radio("掃描模式", ["精選觀察名單", "🔥 全台股大掃描 (6mo 暖機)"])

col1, col2, col3 = st.columns(3)
col1.metric("大盤位置 (基準日)", f"{idx_today['Close']:.2f}")
col2.metric("市場寬度", f"{idx_today['Breadth']:.1%}")
col3.metric("大盤神盾", "🛡️ ON" if shield_on else "⚠️ OFF")

st.subheader(f"🎯 狙擊目標清單 ({last_date.date()})")

if scan_mode == "🔥 全台股大掃描 (6mo 暖機)":
    # 雙按鈕介面
    cA, cB = st.columns([1,1])
    with cA:
        start_scan = st.button("🚀 啟動全市場自動偵蒐")
    with cB:
        if st.button("⛔ 停止掃描"):
            st.session_state.stop_scan = True
            st.rerun()

    if start_scan:
        st.session_state.stop_scan = False
        all_codes = get_all_taiwan_symbols()
        
        # 名單數量異常檢查
        if len(all_codes) < 500:
            st.error(f"❌ 名單取得異常（僅 {len(all_codes)} 檔），請檢查來源網頁或稍後再試。")
            st.stop()
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        results, error_count = [], 0
        
        for i, s in enumerate(all_codes):
            if st.session_state.stop_scan:
                st.warning("已停止掃描。")
                break
                
            status_text.text(f"正在偵蒐: {s} ({i+1}/{len(all_codes)})")
            progress_bar.progress((i + 1) / len(all_codes))
            
            try:
                # auto_adjust=False 確保口徑一致
                df = yf.download(s, period="6mo", progress=False, auto_adjust=False)
                if len(df) < 60: continue
                
                ma50 = df['Close'].rolling(50).mean().iloc[-1]
                high20 = df['High'].rolling(20).max().shift(1).iloc[-1]
                close = df['Close'].iloc[-1]
                vol = df['Volume'].iloc[-1]
                
                if pd.isna(vol) or vol <= 0 or pd.isna(ma50) or pd.isna(high20) or pd.isna(close): 
                    continue
                
                # 流動性粗濾 (4,000 萬)
                val = close * vol
                if val < 40_000_000: continue
                
                # 突破判定
                if 30 <= close <= 300 and close > high20 and close > ma50:
                    results.append({"代號": s, "現價": round(close, 2), "狀態": "🎯 突破"})
            except:
                error_count += 1
                continue
            
        if error_count > 0:
            st.caption(f"ℹ️ 掃描期間共有 {error_count} 檔下載異常已自動跳過。")
            
        if results:
            st.success(f"✅ 掃描完成！發現 {len(results)} 檔標的。")
            st.table(pd.DataFrame(results))
        else:
            st.info("今日全台股無符合標的。")
else:
    # 精選池完整掃描
    rs_val = rs_thresholds.loc[last_date]
    signals = TitanOpp.find_signals(target_symbols, all_data, idx_today, rs_val, [])
    
    if signals:
        rows = []
        for s in signals:
            bar = all_data[s].loc[last_date]
            rs_score = float(bar['RS_Score']) if (not pd.isna(bar['RS_Score'])) else None
            vol_mult = (bar['Volume'] / bar['VolMA20']) if (not pd.isna(bar['VolMA20']) and bar['VolMA20'] > 0) else np.nan
            avg_val20 = int(bar['AvgVal20']) if (not pd.isna(bar['AvgVal20'])) else None
            atr = float(bar['ATR']) if (not pd.isna(bar['ATR'])) else None
            entry = float(bar['Close'])
            
            if atr is None:
                sl, tp1 = None, None
            else:
                sl = max(entry * 0.95, entry - 1.5 * atr)
                tp1 = max(entry * 1.05, entry + (entry - sl))
            
            rows.append({
                "代號": s,
                "收盤價": round(entry, 2),
                "RS_Score": round(rs_score, 4) if rs_score is not None else None,
                "量能倍數(V/20MA)": round(vol_mult, 2) if not pd.isna(vol_mult) else None,
                "20日均成交值": avg_val20,
                "🚩 停損位(參考)": round(sl, 2) if sl is not None else None,
                "🚀 停利位(參考)": round(tp1, 2) if tp1 is not None else None
            })
        st.success(f"精選池偵測到 {len(signals)} 檔符合全條件目標！")
        st.table(pd.DataFrame(rows))
    else:
        st.warning("精選池目前未達標，請耐心等待訊號。")

st.markdown("---")
st.caption(f"數據更新基準日：{last_date} | 鋼鐵泰坦 v11.9 PRO")
