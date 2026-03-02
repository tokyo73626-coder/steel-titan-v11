import pandas as pd
import os

# 定義 V2.4 完整欄位 (必須完全對齊，否則 secure_read 會報錯)
watch_cols = ['sym', 'price', 'target', 'rs_score', 'stop_loss', 'atr', 'news_risk', 'news_score', 'type']

# 建立一筆測試數據
test_data = [{
    'sym': '2330.TW',
    'price': 1000.0,
    'target': 1000.0,
    'rs_score': 0.85,
    'stop_loss': 970.0,
    'atr': 20.0,
    'news_risk': '🟢 安全',
    'news_score': 95,
    'type': 'BK (趨勢突破)'
}]

df = pd.DataFrame(test_data)

# 強制寫入檔案
df.to_csv('tomorrow_watchlist.csv', index=False)
print("✅ 測試數據已成功注入 tomorrow_watchlist.csv")