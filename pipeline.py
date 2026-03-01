import yfinance as yf
import pandas as pd
import numpy as np

def get_titan_data(symbols, benchmark, start_date, end_date):
    # 暖機期 (提早一年)
    data_start = (pd.to_datetime(start_date) - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
    
    idx = yf.download(benchmark, start=data_start, end=end_date, auto_adjust=False)
    if isinstance(idx.columns, pd.MultiIndex): idx.columns = idx.columns.get_level_values(0)
    
    # 大盤神盾指標
    idx['MA50'] = idx['Close'].rolling(50).mean()
    idx['MA50_Slope'] = idx['MA50'] > idx['MA50'].shift(1)
    idx['RS_Base_63'] = idx['Close'].pct_change(63)
    idx['RS_Base_21'] = idx['Close'].pct_change(21)
    
    breadth_matrix = pd.DataFrame(index=idx.index)
    all_data = {}
    
    for s in symbols:
        df = yf.download(s, start=data_start, end=end_date, auto_adjust=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.reindex(idx.index)
        
        # 核心技術指標
        df['MA50'] = df['Close'].rolling(50).mean()
        df['High20'] = df['High'].rolling(20).max()
        df['VolMA20'] = df['Volume'].rolling(20).mean().shift(1)
        df['AvgVal20'] = (df['Close'] * df['Volume']).rolling(20).mean().shift(1)
        
        # ATR 計算
        pc = df['Close'].shift(1)
        tr = pd.concat([df['High']-df['Low'], (df['High']-pc).abs(), (df['Low']-pc).abs()], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        # RS Score ($0.7 \times RS_{63} + 0.3 \times RS_{21}$)
        rs63 = df['Close'].pct_change(63) - idx['RS_Base_63'].reindex(df.index)
        rs21 = df['Close'].pct_change(21) - idx['RS_Base_21'].reindex(df.index)
        df['RS_Score'] = (rs63 * 0.7) + (rs21 * 0.3)
        
        breadth_matrix[s] = (df['Close'] > df['MA50']).astype(int)
        all_data[s] = df
        
    # 精確寬度計算
    denom = max(1, breadth_matrix.shape[1])
    market_breadth = breadth_matrix.sum(axis=1) / denom
    idx['Breadth'] = market_breadth
    idx['Breadth_MA5'] = market_breadth.rolling(5).mean()
    
    # RS 門檻計算安全化
    rs_df = pd.DataFrame({s: all_data[s]['RS_Score'] for s in all_data})
    rs_thresholds = rs_df.quantile(0.8, axis=1, interpolation='linear')
    
    return idx, all_data, rs_thresholds