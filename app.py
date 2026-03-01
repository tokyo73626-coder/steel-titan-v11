import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import io, requests, time
from datetime import datetime, timedelta
from typing import Optional 
from pipeline import get_titan_data
from opp import TitanOpp

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
    相容 Python 3.9+ 部署環境。
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
    levels = cols.nlevels
    ticker_level = None
    for lv in range(levels):
        if ticker in set(cols.get_level_values(lv)):
            ticker_level = lv
            break
    if ticker_level is None:
        return None

    sub = df_batch.xs(ticker, axis=1, level=ticker_level, drop_level=True)

    # 壓平多層欄位並去除重複
    if isinstance(sub.columns, pd.MultiIndex):
        sub.columns = [c[0] if isinstance(c, tuple) else c for c in sub.columns]
    
    sub = sub.loc[:, ~pd.Index(sub.columns).duplicated(keep="last")]

    # Close 補位
    if "Close" not in sub.columns and "Adj Close" in sub.columns:
        sub = sub.copy()
        sub["Close"] = sub["Adj Close"]

    if {"Close"}.issubset(set(sub.columns)) and need_min.issubset(set(sub.columns)):
        return sub

    return None

# --- [3. 高效快取函數] ---
@st.cache_data(ttl=86400)
def get_all_taiwan_symbols():
    url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    def fetch_codes(url, suffix):
        out = []
        try:
            r = requests.get(url, timeout=15, headers=headers)
            r.encoding = 'cp950'
            df = pd.read_html(io.StringIO(r.text))[0]
            df.columns = df.iloc[0]
            codes = df.iloc[1:]['有價證券代號及名稱'].astype(str).str.split('　').str[0]
            for c in codes:
                if c.isdigit() and len(c) == 4:
                    out.append(f"{c}.{suffix}")
        except Exception:
            st.warning(f"⚠️ 抓取 {suffix} 名單失敗")
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

# --- [4. UI 佈局與數據對齊] ---
st.set_page_config(page_title="鋼鐵泰坦 v11.9 PRO", layout="wide")
st.title("🛡️ 鋼鐵泰坦 v11.9：生產級雲端穩定版")

with st.spinner('📡 衛星精準校準中 (長跑穩健模式)...'):
    breadth_key = tuple(BREADTH_POOL)
    target_key = tuple(sorted(st.session_state.target_pool))
    
    idx, env_data, rs_thresholds = load_env_system(breadth_key)
    pool_data = load_pool_data(target_key)
    
    # [同源鎖定]
    need = ['Close','MA50','MA50_Slope','Breadth','Breadth_MA5']
    rs_series = rs_thresholds.reindex(idx.index)
    valid_mask = idx[need].notna().all(axis=1) & rs_series.notna()
    
    if not valid_mask.any():
        st.error("❌ 無法對齊環境資料。")
        st.stop()
    
    last_date = idx.index[valid_mask][-1]
    idx_today = idx.loc[last_date]
    rs_val = float(rs_series.loc[last_date])
    shield_on = (idx_today['Close'] > idx_today['MA50']) and bool(idx_today['MA50_Slope'])

# Sidebar
st.sidebar.header("📡 任務控制中心")
scan_mode = st.sidebar.radio("模式選擇", ["🎯 動態池監控 (抗洗模式)", "🚀 全市場超音速掃描"])

if "prev_mode" not in st.session_state: st.session_state.prev_mode = scan_mode
if st.session_state.prev_mode != scan_mode:
    st.session_state.stop_scan = False
    st.session_state.prev_mode = scan_mode

st.sidebar.markdown(f"---")
st.sidebar.metric("監控池規模", f"{len(st.session_state.target_pool)} 檔")
if st.sidebar.button("♻️ 重設名單"):
    st.session_state.target_pool = sorted(list(set(BREADTH_POOL)))
    st.session_state.stop_scan = False
    st.rerun()

# 儀表板
col1, col2, col3 = st.columns(3)
col1.metric("基準交易日", f"{last_date.date()}")
col2.metric("RS 強度門檻", f"{rs_val:.4f}")
col3.metric("大盤神盾", "🛡️ ON" if shield_on else "⚠️ OFF")

# --- [5. 核心模組：超音速掃描] ---

if scan_mode == "🚀 全市場超音速掃描":
    cA, cB = st.columns([1,1])
    with cA: start_scan = st.button("🚀 啟動兩段式偵蒐")
    with cB:
        if st.button("⛔ 停止掃描"):
            st.session_state.stop_scan = True
            st.rerun()

    if start_scan:
        st.session_state.stop_scan = False
        all_codes = get_all_taiwan_symbols()
        if len(all_codes) < 500: st.stop()
            
        progress_bar = st.progress(0); status_text = st.empty()
        candidates, dl_err_count, skip_count = set(), 0, 0
        proc_err_count, last_proc_err = 0, ""
        
        batch_size = 50 
        for i in range(0, len(all_codes), batch_size):
            if st.session_state.stop_scan: break
            
            chunk = all_codes[i : i + batch_size]
            done = min(i + batch_size, len(all_codes))
            # [修正 1] UI 語意明確化：標註為「檔數」
            status_text.text(f"🚀 偵蒐：{done}/{len(all_codes)} | 下載異常(檔數)：{dl_err_count} | 處理噴錯：{proc_err_count} | 跳過：{skip_count} | 候選：{len(candidates)}")
            progress_bar.progress(done / len(all_codes))
            
            try:
                try:
                    df_batch = yf.download(tickers=chunk, period="6mo", group_by='ticker', progress=False, auto_adjust=False, threads=False)
                except:
                    df_batch = yf.download(tickers=chunk, period="6mo", group_by='ticker', progress=False, auto_adjust=False)
                
                # [修正 2] 結構檢查更嚴謹
                if df_batch is None or df_batch.empty:
                    dl_err_count += len(chunk)
                    continue
                if len(chunk) > 1:
                    if not isinstance(df_batch.columns, pd.MultiIndex):
                        dl_err_count += len(chunk)
                        continue

                for s in chunk:
                    try:
                        df = pick_one_ticker_ohlcv(df_batch, s)
                        if df is None or df.empty or len(df) < 60:
                            skip_count += 1
                            continue

                        df = df[~df.index.duplicated(keep="last")].sort_index()

                        # 時間錨定
                        base = df[['Close','High','Volume']].dropna()
                        base_le = base.loc[:last_date] 
                        if base_le.empty:
                            skip_count += 1
                            continue
                        t = base_le.index[-1] 

                        cc, vv = df.at[t, 'Close'], df.at[t, 'Volume']
                        if pd.isna(cc) or pd.isna(vv):
                            skip_count += 1
                            continue
                        
                        c, v = float(cc), float(vv)
                        if not (np.isfinite(c) and np.isfinite(v)) or v <= 0:
                            skip_count += 1
                            continue

                        h20_s = df['High'].rolling(20).max().shift(1)
                        m50_s = df['Close'].rolling(50).mean()
                        avg_s = (df['Close'] * df['Volume']).rolling(20).mean().shift(1)

                        # KeyError 防守
                        try:
                            h20 = h20_s.loc[t]
                            m50 = m50_s.loc[t]
                            avg_val20_approx = avg_s.loc[t]
                        except KeyError:
                            skip_count += 1
                            continue
                        
                        if pd.isna(h20) or pd.isna(m50) or pd.isna(avg_val20_approx):
                            skip_count += 1
                            continue

                        if (c > h20) and (c > m50) and (30 <= c <= 300) and (avg_val20_approx >= 40_000_000) and (c*v >= 40_000_000):
                            candidates.add(s)

                    except Exception as e:
                        proc_err_count += 1
                        last_proc_err = str(e)
                        continue
                
                time.sleep(0.8)
            except Exception:
                dl_err_count += len(chunk)
                continue
            
        if proc_err_count > 0:
            st.caption(f"ℹ️ 單檔處理噴錯：{proc_err_count} | 最後錯誤：{last_proc_err}")

        if candidates:
            cand_list = sorted(list(candidates))
            st.info(f"🔍 發現 {len(cand_list)} 檔候選，進行分批 Titan 複驗...")
            
            end_for_cand = (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            confirmed = []
            for j in range(0, len(cand_list), 50):
                batch = cand_list[j : j + 50]
                _, cand_data, _ = get_titan_data(batch, "0050.TW", "2025-01-01", end_for_cand)
                confirmed.extend(TitanOpp.find_signals(batch, cand_data, idx_today, rs_val, []))
                time.sleep(0.5)

            confirmed = sorted(list(set(confirmed)))
            old_set, new_confirmed_set = set(st.session_state.target_pool), set(confirmed)
            
            if not new_confirmed_set.issubset(old_set):
                st.session_state.target_pool = sorted(list(set(st.session_state.target_pool) | new_confirmed_set))
                st.success(f"🔥 正式納入 {len(new_confirmed_set - old_set)} 檔新標的。")
                st.rerun()
            elif confirmed:
                st.warning("✅ 複驗完成，標的均已在監控中。")
            else:
                st.warning(f"⚠️ 粗篩有 {len(cand_list)} 檔，但均未通過複驗。")
                
            if confirmed: st.table(pd.DataFrame({"正式確認標的": confirmed}))
        else:
            st.info(f"今日無符合標的 (異常統計：{dl_err_count} | 跳過：{skip_count})")

else:
    # 🎯 動態池監控 (抗洗模式)
    signals = TitanOpp.find_signals(st.session_state.target_pool, pool_data, idx_today, rs_val, [])
    survivors, display_rows = [], []
    
    for s in st.session_state.target_pool:
        if s not in pool_data: continue
        df_s = pool_data[s].loc[:last_date].tail(5)
        
        if len(df_s) >= 3 and df_s['Close'].tail(3).isna().all(): continue 
        if len(df_s) < 3 or df_s[['Close','MA50']].tail(3).isna().any().any():
            survivors.append(s); continue
            
        if (df_s['Close'].tail(3) < df_s['MA50'].tail(3) * 0.97).all(): continue 
            
        survivors.append(s)
        
        if s in signals:
            bar = pool_data[s].loc[last_date]
            # [修正 3] ATR 取值極端防守
            atr = bar['ATR'] if ('ATR' in bar and not pd.isna(bar['ATR'])) else None
            sl_v = max(bar['Close'] * 0.95, bar['Close'] - 1.5 * atr) if atr else bar['Close'] * 0.95
            
            display_rows.append({
                "代號": s, "現價": round(bar['Close'], 2), "RS_Score": round(float(bar['RS_Score']), 4),
                "量能倍數": round(bar['Volume'] / bar['VolMA20'], 2) if bar['VolMA20'] > 0 else 0,
                "🚩 停損位": f"{round(sl_v, 2)}" + ("" if atr else " (5%代)")
            })

    new_pool_sorted = sorted(list(set(survivors)))
    if new_pool_sorted != st.session_state.target_pool:
        st.session_state.target_pool = new_pool_sorted
        st.toast(f"🧹 已自動清理弱勢標的")
        st.rerun() 
        
    if display_rows:
        st.success(f"🔥 動態池中有 {len(display_rows)} 檔符合突破條件！")
        st.table(pd.DataFrame(display_rows))
    else:
        st.warning("監控池穩定運作中。")

st.markdown("---")
st.caption(f"數據基準：{last_date.date()} | 鋼鐵泰坦 v11.9 PRO | 生產級雲端穩定版")
