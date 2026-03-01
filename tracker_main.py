import pandas as pd
import os
from pipeline import get_titan_data
from opp import TitanOpp
from notifier import send_line_msg

SYMBOLS_POOL = ["2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW", "1513.TW", "1519.TW", "1605.TW", "2618.TW", "2308.TW", "2376.TW", "2449.TW", "3034.TW", "3037.TW", "1503.TW", "3711.TW"]
LINE_TOKEN = os.getenv("LINE_TOKEN", "YOUR_LINE_TOKEN")
FEE, TAX, SLIP, MIN_F = 0.001425 * 0.28, 0.003, 0.001, 20

def run_position_tracker():
    print("🛡️ 鋼鐵泰坦 v11.9：監控持倉任務啟動...")
    try:
        df = pd.read_csv('tracker.csv')
        if df.empty: return
    except: return

    today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
    idx, all_data, _ = get_titan_data(SYMBOLS_POOL, "0050.TW", "2025-01-01", today_str)
    
    valid_mask = idx[['Close', 'MA50', 'MA50_Slope', 'Breadth', 'Breadth_MA5']].notna().all(axis=1)
    if not valid_mask.any(): return
    
    today_date = idx.index[valid_mask][-1]
    idx_today = idx.loc[today_date]
    shield_on = (idx_today['Close'] > idx_today['MA50']) and bool(idx_today['MA50_Slope'])
    
    print(f"📅 基準日: {today_date.date()} | 神盾: {'✅' if shield_on else '❌'}")
    
    alert_list, has_action = [], False
    for _, row in df.iterrows():
        sym = row['sym']
        if sym not in all_data or today_date not in all_data[sym].index: continue
        bar = all_data[sym].loc[today_date]
        
        # stage1_done 審計解析
        val = row['stage1_done']
        stage1_done = val.strip().lower() in ['true','1','yes','y'] if isinstance(val, str) else (False if pd.isna(val) else bool(val))
        
        # 交易日抗脆弱對齊
        ent_d = pd.to_datetime(row['entry_date'])
        if ent_d > today_date:
            print(f"{sym:<8} ⚠️ entry_date 晚於今日，跳過")
            continue
            
        pos = idx.index.get_indexer([ent_d], method='bfill')[0]
        if pos == -1:
            print(f"{sym:<8} ⚠️ entry_date 無法對齊交易日，跳過")
            continue
        aligned_d = idx.index[pos]
        
        hold_days = idx.index.get_loc(today_date) - idx.index.get_loc(aligned_d)
        old_sl = float(row['trailing_sl'])
        trade = {'sym': sym, 'entry_p': float(row['entry_p']), 'trailing_sl': old_sl, 'tp1': float(row['tp1']), 'stage1_done': stage1_done}
        
        reason, _, _ = TitanOpp.check_exit(trade, bar, idx_today['Breadth'], hold_days, SLIP, FEE, TAX, MIN_F)
        
        new_sl = float(trade['trailing_sl'])
        if reason:
            has_action = True
            msg = f"🚩 {sym} | 狀態: {reason}!\n現價: {bar['Close']:.2f} | 停損位: {new_sl:.2f}\n"
            msg += "📢 動作：賣 1/3 更新 CSV" if reason=="ST1_TP" else "📢 動作：明日開盤全出"
            alert_list.append(msg)
        
        print(f"{sym:<8} {bar['Close']:<7.2f} SL: {old_sl:.1f}->{new_sl:.1f} {'↑' if new_sl > old_sl+0.01 else ''} {reason if reason else '穩定'}")

    if has_action: send_line_msg(LINE_TOKEN, f"\n🛡️【鋼鐵泰坦持倉警報】\n" + "\n".join(alert_list))

if __name__ == "__main__":
    run_position_tracker()