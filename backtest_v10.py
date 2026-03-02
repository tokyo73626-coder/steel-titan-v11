import yfinance as yf
import pandas as pd
import os
from datetime import datetime
from notifier import send_tg_msg  # 💡 匯入你的 Telegram 通訊模組

# --- 1. 定義股票池與所屬族群 ---
INDUSTRY_MAP = {
    "2330.TW": "半導體", "2454.TW": "半導體", "3711.TW": "半導體", "2308.TW": "半導體",
    "2317.TW": "AI組裝", "2382.TW": "AI組裝", "3231.TW": "AI組裝", "2376.TW": "AI組裝",
    "1513.TW": "重電綠能", "1519.TW": "重電綠能", "1605.TW": "重電綠能", "1503.TW": "重電綠能",
    "2618.TW": "航運", "2603.TW": "航運", "2609.TW": "航運",
    "2449.TW": "電子零組件", "3034.TW": "面板驅動", "3037.TW": "ABF載板"
}
SYMBOLS = list(INDUSTRY_MAP.keys())

def run_scan():
    base_path = os.path.dirname(os.path.abspath(__file__))
    watchlist_path = os.path.join(base_path, "tomorrow_watchlist.csv")
    sector_path = os.path.join(base_path, "sector_momentum.csv")
    
    cols = ['sym', 'price', 'target', 'rs_score', 'stop_loss', 'atr', 'news_risk', 'news_score', 'sector', 'type']
    results = []
    sector_rs = {}
    sector_count = {}

    try:
        data = yf.download(SYMBOLS, period="3mo", auto_adjust=True, progress=False)
        for s in SYMBOLS:
            try:
                df = data.xs(s, axis=1, level=1).dropna()
                if len(df) < 20: continue
                
                curr_p = round(df['Close'].iloc[-1], 2)
                high20 = round(df['High'].rolling(20).max().iloc[-1], 2)
                rs_20 = df['Close'].pct_change(20).iloc[-1]
                sector = INDUSTRY_MAP.get(s, "其他")
                
                sector_rs[sector] = sector_rs.get(sector, 0) + rs_20
                sector_count[sector] = sector_count.get(sector, 0) + 1
                
                if curr_p >= (high20 * 0.98):
                    pc = df['Close'].shift(1)
                    atr = pd.concat([df['High']-df['Low'], (df['High']-pc).abs(), (df['Low']-pc).abs()], axis=1).max(axis=1).rolling(14).mean().iloc[-1]
                    
                    results.append({
                        'sym': s, 'price': curr_p, 'target': high20, 'rs_score': round(rs_20 * 100, 2),
                        'stop_loss': round(curr_p - (1.5 * atr), 2), 'atr': round(atr, 2),
                        'news_risk': '🟢 安全', 'news_score': 90, 'sector': sector, 'type': 'BK (趨勢突破)'
                    })
            except: continue
        
        sector_data = [{'sector': k, 'avg_rs': round((v / sector_count[k]) * 100, 2)} for k, v in sector_rs.items()]
        pd.DataFrame(sector_data).sort_values(by='avg_rs', ascending=False).to_csv(sector_path, index=False)
        
        df_res = pd.DataFrame(results if results else [], columns=cols)
        df_res.to_csv(watchlist_path, index=False)
        
        # 💡 V7.0 推播邏輯：如果有掃描到標的，就發送 Telegram
        if results:
            msg = f"🎯 <b>獵人掃描報告 ({datetime.now().strftime('%H:%M')})</b>\n\n"
            msg += f"發現 {len(results)} 檔符合突破鐵律：\n"
            for r in results:
                msg += f"🔹 <b>{r['sym']}</b> ({r['sector']})\n"
                msg += f"   現價: {r['price']} | 停損: {r['stop_loss']}\n"
            msg += "\n👉 請開啟戰情室確認是否執行買入。"
            
            send_tg_msg(msg) # 呼叫 notifier.py 傳送訊息
            print(f"✅ 掃描完成，已發送 Telegram 通知。找到 {len(results)} 檔。")
        else:
            print(f"✅ 掃描完成，目前無符合標的。")
            
    except Exception as e:
        print(f"❌ 錯誤: {e}")

if __name__ == "__main__":
    run_scan()