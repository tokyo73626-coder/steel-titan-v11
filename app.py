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
@
