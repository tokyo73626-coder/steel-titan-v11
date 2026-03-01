import pandas as pd

class TitanOpp:
    @staticmethod
    def find_signals(symbols, all_data, idx_today, rs_threshold, active_trades):
        signals = []
        PRICE_FLOOR, PRICE_CEILING = 30.0, 300.0
        
        # 1. 環境防線
        mkt_ok = idx_today['Close'] > idx_today['MA50'] and bool(idx_today['MA50_Slope'])
        breadth_ok = idx_today['Breadth'] >= 0.30 and idx_today['Breadth'] >= idx_today['Breadth_MA5']
        
        if not (mkt_ok and breadth_ok): return []

        held_syms = [t['sym'] for t in active_trades]
        vol_threshold = 1.2 if idx_today['Breadth'] > 0.5 else 1.5

        for s in symbols:
            if s in held_syms: continue
            df = all_data.get(s)
            if df is None or len(df) < 50: continue
            
            today_s = df.loc[idx_today.name]
            
            # NaN 防守
            need = ['Close','High20','MA50','RS_Score','Volume','VolMA20','AvgVal20']
            if today_s[need].isna().any(): continue
            
            # ✅ 修正 1：避免熱區重算，單次提取數值
            prev_high20_val = df['High20'].shift(1).loc[idx_today.name]
            price_ok = (today_s['Close'] >= prev_high20_val) and (today_s['Close'] > today_s['MA50'])
            
            # 其餘濾網
            price_range = PRICE_FLOOR <= today_s['Close'] <= PRICE_CEILING
            rs_ok = today_s['RS_Score'] >= rs_threshold and today_s['RS_Score'] > 0
            vol_ok = today_s['Volume'] > today_s['VolMA20'] * vol_threshold
            val_ok = today_s['AvgVal20'] >= 40000000
            
            if price_ok and rs_ok and vol_ok and val_ok and price_range:
                signals.append(s)
        return signals

    @staticmethod
    def check_exit(trade, bar, current_breadth, hold_days, slip, fee, tax, min_f):
        # 核心參數防呆
        if pd.isna(bar['Close']) or pd.isna(trade['entry_p']): 
            return None, None, False
            
        profit_pct = (bar['Close'] / trade['entry_p']) - 1
        
        # 移動停損機制
        be_target = 0.03 if current_breadth < 0.5 else 0.05
        if profit_pct >= be_target:
            trade['trailing_sl'] = max(trade['trailing_sl'], trade['entry_p'] * 1.005)
            
        # ✅ 修正 2：補強 ATR NaN 防守，避免 trailing_sl 毀損
        if profit_pct >= 0.08 and (not pd.isna(bar['ATR'])):
            trade['trailing_sl'] = max(trade['trailing_sl'], bar['Close'] - 2.5 * bar['ATR'])
        
        # 出場判定
        hit_tp1 = (not trade['stage1_done']) and (bar['High'] >= trade['tp1'])
        hit_sl = (bar['Low'] <= trade['trailing_sl'])
        
        if hit_tp1 and hit_sl: return "STOP_LOSS", trade['trailing_sl'], False
        if hit_tp1: return "ST1_TP", trade['tp1'], True
        if hit_sl: return "STOP_LOSS", trade['trailing_sl'], False
        if bar['Close'] < bar['MA50'] * 0.99 and hold_days >= 10: return "MA50_EXIT", bar['Close'], False
        return None, None, False