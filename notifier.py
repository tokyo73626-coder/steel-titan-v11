import requests

# 🔑 填入你的專屬金鑰與 ID
TOKEN = "8143074019:AAFCodmZC1WGXGFBmkN7edjzjz7hHo8vvyc"  # 例如 "1234567890:AAH_xxx..."
CHAT_ID = "8671187793" # 例如 "123456789"

def send_tg_msg(msg):
    """傳送 Telegram 訊息的專屬函數"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML" # 允許使用粗體等簡單排版
        }
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print("✅ Telegram 訊息發送成功！")
        else:
            print(f"❌ 發送失敗，錯誤碼: {res.status_code}")
    except Exception as e:
        print(f"❌ 傳送發生異常: {e}")

# 👇 這是測試用的代碼，只有直接執行這個檔案時才會觸發
if __name__ == "__main__":
    test_message = """
    🚨 <b>小秉交易系統 V7.0 上線測試</b> 🚨
    
    指揮官您好，您的專屬通訊模組已成功啟動！
    這代表未來只要有：
    🎯 <b>新標的突破</b>
    💰 <b>達到停利目標</b>
    🛡️ <b>觸發停損防線</b>
    
    我都會第一時間回報到您的手機！
    """
    send_tg_msg(test_message)