import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import io, requests, time
from datetime import datetime, timedelta
from typing import Optional 
from pipeline import get_titan_data
from opp import TitanOpp

# 關閉 SSL 警告 (僅針對特定連線)
import urllib3
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
    支援多層 MultiIndex 擷取與欄位名變體補位。相容 Python 3.9+。
    """
    if df_batch is None or df_batch.empty:
        return None

    cols = df_batch.columns
    need_min = {"High", "Volume"}

    if not isinstance(cols, pd.MultiIndex):
        if "Close" not in cols and "Adj Close" in cols:
            tmp = df_batch.copy()
            tmp["Close"] = tmp["Adj Close"]
            df_batch = tmp
            cols = df_batch.columns
        if {"Close"}.issubset(set(cols)) and need_min.issubset(set(cols)):
            return df_batch
        return None

    levels = cols.nlevels
    ticker_level = None
    for lv in range(levels):
        if ticker in set(cols.get_level_values(lv)):
            ticker_level = lv
            break
    if ticker_level is None:
        return None

    sub = df_batch.xs(ticker, axis=1, level=ticker_level, drop_level=True)

    if isinstance(sub.columns, pd.MultiIndex):
        sub.columns = [c[0] if isinstance(c, tuple) else c for c in sub.columns]
    
    sub = sub.loc[:, ~pd.Index(sub.columns).duplicated(keep="last")]

    if "Close" not in sub.columns and "Adj Close" in sub.columns:
        sub = sub.copy()
        sub["Close"] = sub["Adj Close"]

    if {"Close"}.issubset(set(sub.columns)) and need_min.issubset(set(sub.columns)):
        return sub

    return None

# --- [3. 診斷式名單抓取] ---
@st.cache_data(ttl=86400)
def get_all_taiwan_symbols():
    urls = {"TW": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", 
            "TWO": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    all_out = []
    for suffix, url in urls.items():
        try:
            r = requests.get(url, timeout=(8, 20), headers=headers, verify=False)
            r.raise_for_status()
            try: r.encoding = "cp950"
            except: r.encoding = r.apparent_encoding
            tables = pd.read_html(io.StringIO(r.text))
            if not tables: raise ValueError("read_html: no tables")
            df = tables[0]; df.columns = df.iloc[0]
            codes = df.iloc[1:]["有價證券代號及名稱"].astype(str).str.split("　").str[0]
            all_out.extend([f"{c}.{suffix}" for c in codes if c.isdigit() and len(c) == 4])
        except Exception as e:
            st.warning(f"⚠️ 抓取 {suffix} 名單失敗：{type(e).__name__} | {e}")
    
    final_list = sorted(list(set(all_out)))
    if len(final_list) < 500:
        raise RuntimeError(f"偵蒐名單異常 (僅抓到 {len(final_list)} 檔)。可能是連線被阻擋或 SSL/DNS 問題。")
    return final_list

# --- [4. 環境快取函數] ---
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

# --- [5. UI 與數據對齊] ---
st.set_page_config(page_title="鋼鐵泰坦 PRO", layout="wide")
st.title("🛡️ 鋼鐵泰坦 v11.9：不倒翁降級防禦版")

with st.spinner('📡 衛星對齊環境基準中...'):
    idx, env_data, rs_thresholds = load_env_system(tuple(BREADTH_POOL))
    pool_data = load_pool_data(tuple(sorted(st.session_state.target_pool)))
    rs_series = rs_thresholds.reindex(idx.index)
    valid_mask = idx[['Close','MA50','MA50_Slope','Breadth','Breadth_MA5']].notna().all(axis=1) & rs_series.notna()
    if not valid_mask.any(): st.error("❌ 環境資料對齊失敗"); st.stop()
    last_date = idx.index[valid_mask][-1]
    idx_today, rs_val = idx.loc[last_date], float(rs_series.loc[last_date])
    shield_on = (idx_today['Close'] > idx_today['MA50']) and bool(idx_today['MA50_Slope'])

# 側邊欄與儀表板
st.sidebar.header("📡 任務控制中心")
scan_mode = st.sidebar.radio("模式切換", ["🎯 動態池監控 (抗洗模式)", "🚀 全市場超音速掃描"])
if st.sidebar.button("♻️ 重設名單"):
    st.session_state.target_pool = sorted(list(set(BREADTH_POOL)))
    st.session_state.stop_scan = False; st.rerun()

col1, col2, col3 = st.columns(3)
col1.metric("數據快照基準日 (收盤)", f"{last_date.date()}")
col2.metric("環境 RS 門檻", f"{rs_val:.4f}")
col3.metric("大盤神盾", "🛡️ ON" if shield_on else "⚠️ OFF")

# --- [6. 核心偵蒐邏輯] ---
if scan_mode == "🚀 全市場超音速掃描":
    cA, cB = st.columns([1,1]); start_btn = cA.button("🚀 啟動兩段式偵蒐")
    if cB.button("⛔ 停止掃描"): st.session_state.stop_scan = True; st.rerun()

    if start_btn:
        st.session_state.stop_scan = False
        
        try:
            all_codes = get_all_taiwan_symbols()
            st.caption(f"✅ 全市場名單載入成功：{len(all_codes)} 檔")
        except Exception as e:
            st.error(f"⚠️ 全市場名單抓取失敗，已自動降級為監控池掃描：{type(e).__name__} | {e}")
            all_codes = sorted(list(set(st.session_state.target_pool)))
            
        progress_bar, status_text = st.progress(0), st.empty()
        
        candidates, skip_count = set(), 0
        dl_batch_err, dl_symbol_err = 0, 0
        proc_err_count, last_proc_err = 0, ""
        
        batch_size = 50 
        for i in range(0, len(all_codes), batch_size):
            if st.session_state.stop_scan: break
            
            chunk = all_codes[i : i + batch_size]
            done = min(i + batch_size, len(all_codes))
            status_text.text(f"🚀 偵蒐：{done}/{len(all_codes)} | 異常(批/檔)：{dl_batch_err}/{dl_symbol_err} | 處理噴錯：{proc_err_count} | 跳過：{skip_count} | 候選：{len(candidates)}")
            progress_bar.progress(done / len(all_codes))
            
            try:
                try:
                    df_batch = yf.download(chunk, period="6mo", group_by='ticker', progress=False, threads=False, auto_adjust=False)
                except:
                    df_batch = yf.download(chunk, period="6mo", group_by='ticker', progress=False, auto_adjust=False)
                
                # 嚴謹的 MultiIndex 結構檢查
                if df_batch is None or df_batch.empty:
                    dl_batch_err += 1
                    dl_symbol_err += len(chunk)
                    continue
                if len(chunk) > 1:
                    if not isinstance(df_batch.columns, pd.MultiIndex):
                        dl_batch_err += 1
                        dl_symbol_err += len(chunk)
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
                        
                        # [修正 1] 型別轉換增加 ValueError 防守
                        try:
                            c, v = float(cc), float(vv)
                        except ValueError:
                            skip_count += 1
                            continue

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
                        # [修正 2] 邏輯噴錯同步計入 skip_count 確保總數閉環
                        proc_err_count += 1
                        last_proc_err = str(e)
                        skip_count += 1 
                        continue
                
                time.sleep(0.8)
            except Exception:
                dl_batch_err += 1
                dl_symbol_err += len(chunk)
                continue

        # 統計快照與最後例外儲存
        st.caption(f"ℹ️ 粗篩結束 | 候選:{len(candidates)} | 下載異常(批/檔):{dl_batch_err}/{dl_symbol_err} | 噴錯:{proc_err_count} | 跳過:{skip_count}")
        if proc_err_count > 0:
            st.caption(f"ℹ️ 單檔處理噴錯：{proc_err_count} | 最後錯誤：{last_proc_err}")

        if candidates:
            cand_list = sorted(list(candidates))
            st.info(f"🔍 進入複驗階段：{len(cand_list)} 檔候選標的...")
            
            end_for_cand = (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            confirmed = []
            for j in range(0, len(cand_list), 50):
                batch = cand_list[j : j + 50]
                _, cand_data, _ = get_titan_data(batch, "0050.TW", "2025-01-01", end_for_cand)
                confirmed.extend(TitanOpp.find_signals(batch, cand_data, idx_today, rs_val, []))
                time.sleep(0.5)

            confirmed = sorted(list(set(confirmed)))
            old_set, new_confirmed_set = set(st.session_state.target_pool), set(confirmed)
            
            add_set = new_confirmed_set - old_set
            if add_set:
                st.session_state.target_pool = sorted(list(old_set | new_confirmed_set))
                st.success(f"🔥 鋼鐵泰坦已納入 {len(add_set)} 檔最新強勢標的！"); st.rerun()
            elif confirmed: st.warning("✅ 符合標的均已在監控池中。")
            else: st.warning("⚠️ 候選標的未通過 Titan 完整複驗。")
        else: st.info(f"今日無符合粗篩標的。")

else:
    # 🎯 動態池監控 (抗洗模式)
    signals = TitanOpp.find_signals(st.session_state.target_pool, pool_data, idx_today, rs_val, [])
    survivors, rows = [], []
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
            atr = bar['ATR'] if ('ATR' in bar and not pd.isna(bar['ATR'])) else None
            sl = max(bar['Close'] * 0.95, bar['Close'] - 1.5 * atr) if atr else bar['Close'] * 0.95
            rows.append({"代號": s, "收盤": round(bar['Close'], 2), "RS_Score": round(float(bar['RS_Score']), 4), "量能": round(bar['Volume'] / bar['VolMA20'], 2) if bar['VolMA20'] > 0 else 0, "🚩 停損位": f"{round(sl, 2)}"})
    
    if sorted(list(set(survivors))) != st.session_state.target_pool:
        st.session_state.target_pool = sorted(list(set(survivors))); st.toast("🧹 已清理弱勢標的"); st.rerun() 
    if rows: st.success(f"觸發 Titan 突破訊號標的："); st.table(pd.DataFrame(rows))
    else: st.warning("監控池穩定運作中。")

st.markdown("---")
st.caption(f"數據基準：{last_date.date()} | 鋼鐵泰坦 v11.9 PRO | 降級防禦與數據閉環版")
