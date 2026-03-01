import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import io, requests, time, urllib3
from datetime import datetime, timedelta
from typing import Optional 
from pipeline import get_titan_data
from opp import TitanOpp

# 關閉 SSL 安全警告 (解決雲端抓取證交所名單失敗的問題)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- [1. 架構定義：基準池與動態池初始化] ---
BREADTH_POOL = sorted(list(set([
    "2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW", 
    "1513.TW", "1519.TW", "1605.TW", "2618.TW", "2308.TW", 
    "2376.TW", "2449.TW", "3034.TW", "3037.TW", "1503.TW", "3711.TW"
])))

if "target_pool" not in st.session_state:
    st.session_state.target_pool = sorted(list(set(BREADTH_POOL)))

if "stop_scan" not in st.session_state:
    st.session_state.stop_scan = False

# --- [2. 工具函數：強效結構偵測與單檔抽取] ---
def pick_one_ticker_ohlcv(df_batch: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """
    支援多層 MultiIndex 擷取與欄位名變體補位。
    """
    if df_batch is None or df_batch.empty:
        return None
    cols = df_batch.columns
    need_min = {"High", "Volume"}
    # Case 1: 非 MultiIndex (單檔模式)
    if not isinstance(cols, pd.MultiIndex):
        if "Close" not in cols and "Adj Close" in cols:
            tmp = df_batch.copy()
            tmp["Close"] = tmp["Adj Close"]
            df_batch = tmp
            cols = df_batch.columns
        if {"Close"}.issubset(set(cols)) and need_min.issubset(set(cols)):
            return df_batch
        return None
    # Case 2: MultiIndex (逐層搜尋 Ticker)
    ticker_level = None
    for lv in range(cols.nlevels):
        if ticker in set(cols.get_level_values(lv)):
            ticker_level = lv
            break
    if ticker_level is None: return None
    sub = df_batch.xs(ticker, axis=1, level=ticker_level, drop_level=True)
    if isinstance(sub.columns, pd.MultiIndex):
        sub.columns = [c[0] if isinstance(c, tuple) else c for c in sub.columns]
    sub = sub.loc[:, ~pd.Index(sub.columns).duplicated(keep="last")]
    if "Close" not in sub.columns and "Adj Close" in sub.columns:
        sub = sub.copy()
        sub["Close"] = sub["Adj Close"]
    return sub if {"Close"}.issubset(set(sub.columns)) and need_min.issubset(set(sub.columns)) else None

# --- [3. 高效快取函數：修正連線問題] ---
@st.cache_data(ttl=86400)
def get_all_taiwan_symbols():
    url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    # 使用標準瀏覽器標頭防止被封鎖
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    def fetch_codes(url, suffix):
        out = []
        try:
            # [修正重點] 加入 verify=False 解決雲端 SSL 握手失敗
            r = requests.get(url, timeout=15, headers=headers, verify=False)
            r.encoding = 'cp950'
            df = pd.read_html(io.StringIO(r.text))[0]
            df.columns = df.iloc[0]
            codes = df.iloc[1:]['有價證券代號及名稱'].astype(str).str.split('　').str[0]
            for c in codes:
                if c.isdigit() and len(c) == 4:
                    out.append(f"{c}.{suffix}")
        except Exception:
            st.warning(f"⚠️ 抓取 {suffix} 名單失敗 (雲端連線受限)")
        return out
    return sorted(list(set(fetch_codes(url_twse, "TW") + fetch_codes(url_tpex, "TWO"))))

@st.cache_data(ttl=3600)
def load_env_system(symbols_tuple):
    today_str = datetime.now().strftime('%Y-%m-%d')
    idx, env_data, rs_thresholds = get_titan_data(list(symbols_tuple), "0050.TW", "2025-01-01", today_str)
    return idx, env_data, rs_thresholds

@st.cache_data(ttl=1800)
def load_pool_data(symbols_tuple):
    today_str = datetime.now().strftime('%Y-%m-%d')
    _, pool_data, _ = get_titan_data(list(symbols_tuple), "0050.TW", "2025-01-01", today_str)
    return pool_data

# --- [4. UI 佈局與對齊] ---
st.set_page_config(page_title="鋼鐵泰坦 v11.9 PRO", layout="wide")
st.title("🛡️ 鋼鐵泰坦 v11.9：生產級雲端穩定版")

with st.spinner('📡 衛星精準校準中...'):
    breadth_key, target_key = tuple(BREADTH_POOL), tuple(sorted(st.session_state.target_pool))
    idx, env_data, rs_thresholds = load_env_system(breadth_key)
    pool_data = load_pool_data(target_key)
    rs_series = rs_thresholds.reindex(idx.index)
    valid_mask = idx[['Close','MA50','MA50_Slope','Breadth','Breadth_MA5']].notna().all(axis=1) & rs_series.notna()
    if not valid_mask.any():
        st.error("❌ 無法對齊環境資料。"); st.stop()
    last_date = idx.index[valid_mask][-1]
    idx_today, rs_val = idx.loc[last_date], float(rs_series.loc[last_date])
    shield_on = (idx_today['Close'] > idx_today['MA50']) and bool(idx_today['MA50_Slope'])

# Sidebar
st.sidebar.header("📡 任務控制中心")
scan_mode = st.sidebar.radio("模式選擇", ["🎯 動態池監控 (抗洗模式)", "🚀 全市場超音速掃描"])
if st.sidebar.button("♻️ 重設名單"):
    st.session_state.target_pool = sorted(list(set(BREADTH_POOL)))
    st.session_state.stop_scan = False; st.rerun()

# 儀表板
col1, col2, col3 = st.columns(3)
col1.metric("基準交易日", f"{last_date.date()}")
col2.metric("RS 強度門檻", f"{rs_val:.4f}")
col3.metric("大盤神盾", "🛡️ ON" if shield_on else "⚠️ OFF")

# --- [5. 核心模組] ---
if scan_mode == "🚀 全市場超音速掃描":
    cA, cB = st.columns([1,1])
    with cA: start_scan = st.button("🚀 啟動兩段式偵蒐")
    with cB: 
        if st.button("⛔ 停止掃描"): st.session_state.stop_scan = True; st.rerun()

    if start_scan:
        st.session_state.stop_scan = False
        all_codes = get_all_taiwan_symbols()
        if len(all_codes) < 500: st.stop()
        progress_bar, status_text = st.progress(0), st.empty()
        candidates, dl_err_count, skip_count, proc_err_count = set(), 0, 0, 0
        
        batch_size = 50 
        for i in range(0, len(all_codes), batch_size):
            if st.session_state.stop_scan: break
            chunk = all_codes[i : i + batch_size]
            status_text.text(f"🚀 偵蒐：{min(i+batch_size, len(all_codes))}/{len(all_codes)} | 異常：{dl_err_count} | 跳過：{skip_count} | 候選：{len(candidates)}")
            progress_bar.progress(min(i + batch_size, len(all_codes)) / len(all_codes))
            try:
                try: df_batch = yf.download(tickers=chunk, period="6mo", group_by='ticker', progress=False, auto_adjust=False, threads=False)
                except: df_batch = yf.download(tickers=chunk, period="6mo", group_by='ticker', progress=False, auto_adjust=False)
                if df_batch is None or df_batch.empty or (len(chunk) > 1 and not isinstance(df_batch.columns, pd.MultiIndex)):
                    dl_err_count += len(chunk); continue
                for s in chunk:
                    try:
                        df = pick_one_ticker_ohlcv(df_batch, s)
                        if df is None or df.empty or len(df) < 60: skip_count += 1; continue
                        df = df[~df.index.duplicated(keep="last")].sort_index()
                        base_le = df[['Close','High','Volume']].dropna().loc[:last_date]
                        if base_le.empty: skip_count += 1; continue
                        t = base_le.index[-1]
                        cc, vv = df.at[t, 'Close'], df.at[t, 'Volume']
                        c, v = float(cc), float(vv)
                        if not (np.isfinite(c) and np.isfinite(v)) or v <= 0: skip_count += 1; continue
                        try:
                            h20, m50 = df['High'].rolling(20).max().shift(1).loc[t], df['Close'].rolling(50).mean().loc[t]
                            avg_v = (df['Close'] * df['Volume']).rolling(20).mean().shift(1).loc[t]
                        except KeyError: skip_count += 1; continue
                        if (c > h20) and (c > m50) and (30 <= c <= 300) and (avg_v >= 40_000_000) and (c*v >= 40_000_000):
                            candidates.add(s)
                    except: proc_err_count += 1; continue
                time.sleep(0.8)
            except: dl_err_count += len(chunk); continue
            
        if candidates:
            cand_list = sorted(list(candidates))
            st.info(f"🔍 複驗 {len(cand_list)} 檔標的...")
            confirmed = []
            for j in range(0, len(cand_list), 50):
                batch = cand_list[j : j + 50]
                _, cand_data, _ = get_titan_data(batch, "0050.TW", "2025-01-01", (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
                confirmed.extend(TitanOpp.find_signals(batch, cand_data, idx_today, rs_val, []))
                time.sleep(0.5)
            confirmed = sorted(list(set(confirmed)))
            if not set(confirmed).issubset(set(st.session_state.target_pool)):
                st.session_state.target_pool = sorted(list(set(st.session_state.target_pool) | set(confirmed)))
                st.success(f"🔥 納入 {len(set(confirmed) - set(st.session_state.target_pool))} 檔。"); st.rerun()
            st.table(pd.DataFrame({"確認標的": confirmed}))
        else: st.info(f"今日無符合標的 (異常：{dl_err_count} | 跳過：{skip_count})")

else:
    signals = TitanOpp.find_signals(st.session_state.target_pool, pool_data, idx_today, rs_val, [])
    survivors, rows = [], []
    for s in st.session_state.target_pool:
        if s not in pool_data: continue
        df_s = pool_data[s].loc[:last_date].tail(5)
        if (len(df_s) >= 3 and df_s['Close'].tail(3).isna().all()) or (df_s['Close'].tail(3) < df_s['MA50'].tail(3) * 0.97).all(): continue 
        survivors.append(s)
        if s in signals:
            bar = pool_data[s].loc[last_date]
            atr = bar['ATR'] if ('ATR' in bar and not pd.isna(bar['ATR'])) else None
            sl = max(bar['Close'] * 0.95, bar['Close'] - 1.5 * atr) if atr else bar['Close'] * 0.95
            rows.append({"代號": s, "現價": round(bar['Close'], 2), "RS": round(float(bar['RS_Score']), 4), "量能": round(bar['Volume'] / bar['VolMA20'], 2) if bar['VolMA20'] > 0 else 0, "停損": f"{round(sl, 2)}"})
    if sorted(list(set(survivors))) != st.session_state.target_pool:
        st.session_state.target_pool = sorted(list(set(survivors))); st.toast("🧹 已清理弱勢標的"); st.rerun() 
    if rows: st.success("觸發訊號標的："); st.table(pd.DataFrame(rows))
    else: st.warning("監控池運行中，尚無訊號。")
st.markdown("---")
st.caption(f"數據基準：{last_date.date()} | 鋼鐵泰坦 PRO | 生產級雲端版本")
