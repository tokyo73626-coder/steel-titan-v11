import streamlit as st
import pandas as pd
import os
from datetime import datetime
import yfinance as yf
from notifier import send_tg_msg  # 💡 匯入你的 Telegram 通訊模組

st.set_page_config(page_title="小秉交易系統 V7.0", layout="wide")

# --- 1. 路徑與基礎設定 ---
base_path = os.path.dirname(os.path.abspath(__file__))
watchlist_file = os.path.join(base_path, "tomorrow_watchlist.csv")
real_pos_file = os.path.join(base_path, "real_positions.csv")
history_file = os.path.join(base_path, "trade_history.csv")
sector_file = os.path.join(base_path, "sector_momentum.csv")

watch_cols = ['sym', 'price', 'target', 'rs_score', 'stop_loss', 'atr', 'news_risk', 'news_score', 'sector', 'type']
pos_cols = ['sym','type','entry_date','entry_p','qty','hard_stop','trailing_stop','atr']
hist_cols = ['sym','type','entry_date','exit_date','entry_p','exit_p','qty','pnl','r_multiple', 'target_p', 'slippage']

def secure_read(path, cols=None):
    if not os.path.exists(path) or os.path.getsize(path) < 10:
        if cols: pd.DataFrame(columns=cols).to_csv(path, index=False)
        return pd.DataFrame(columns=cols) if cols else pd.DataFrame()
    df = pd.read_csv(path)
    if cols:
        for c in cols: 
            if c not in df.columns: df[c] = 0
    return df

df_watch = secure_read(watchlist_file, watch_cols)
df_real = secure_read(real_pos_file, pos_cols)
df_sector = secure_read(sector_file)
df_hist = secure_read(history_file, hist_cols)

# --- 2. 大盤多空環境偵測 ---
@st.cache_data(ttl=600)
def get_market_regime():
    try:
        idx_df = yf.Ticker("0050.TW").history(period="3mo")
        curr_p = idx_df['Close'].iloc[-1]
        ma50 = idx_df['Close'].rolling(50).mean().iloc[-1]
        if curr_p >= ma50:
            return "🟢 多頭環境 (0050 > 50MA)", 5
        else:
            return "🔴 空頭警戒 (0050 < 50MA)", 2
    except:
        return "⚪ 偵測中", 5

market_status, max_slots = get_market_regime()

# --- 3. 動態風險計算 ---
current_exposure = 0
total_risk_amt = 0

if not df_real.empty:
    for _, r in df_real.iterrows():
        current_exposure += r['entry_p'] * r['qty'] * 1000
        total_risk_amt += (r['entry_p'] - r['hard_stop']) * r['qty'] * 1000

# --- 4. 介面呈現 (頂部控制台) ---
st.title("🛡️ 小秉交易系統 V7.0 (全自動推播版)")

st.write("🏦 **動態資金與風險雷達**")
c1, c2, c3, c4 = st.columns(4)
c1.metric("大盤環境", market_status)
c2.metric("在倉 Slot", f"{len(df_real)} / {max_slots} 檔")
c3.metric("總曝險 (市值)", f"{int(current_exposure):,} 台幣")
c4.metric("最大潛在虧損", f"{int(total_risk_amt):,} 台幣", delta="-絕對風險", delta_color="inverse")
st.divider()

# --- 5. 分頁佈局 ---
tab1, tab2, tab3 = st.tabs(["🚀 戰情室", "📍 部位與智能出場", "📈 績效分析"])

with tab1:
    st.subheader("🚀 即時作戰清單")
    if not df_watch.empty:
        for i, row in df_watch.iterrows():
            if row['sym'] in df_real['sym'].values: continue
            sector_is_hot = "🔥" if not df_sector.empty and df_sector[df_sector['sector'] == row['sector']]['avg_rs'].iloc[0] > 0 else "❄️"
            
            with st.expander(f"📌 {row['sym']} [{row['sector']}] {sector_is_hot} | RS: {row['rs_score']}%", expanded=True):
                col1, col2, col3, col4 = st.columns([2, 2, 2, 3])
                col1.write(f"新聞風險: {row['news_risk']}")
                col2.metric("現價 (台幣)", row['price'])
                col3.metric("初始停損 (台幣)", row['stop_loss'])
                
                if len(df_real) >= max_slots:
                    col4.error(f"🚨 Slot 已滿 (上限 {max_slots} 檔)")
                else:
                    qty = col4.number_input("預計買入張數", min_value=1, max_value=10, value=1, key=f"qty_{i}")
                    if col4.button(f"執行買入 {row['sym']}", key=f"buy_{i}"):
                        new_pos = pd.DataFrame([{
                            'sym': row['sym'], 'type': row['type'], 'entry_date': datetime.now().strftime("%Y-%m-%d"),
                            'entry_p': row['price'], 'qty': qty, 'hard_stop': row['stop_loss'], 
                            'trailing_stop': row['stop_loss'], 'atr': row['atr']
                        }])
                        pd.concat([df_real, new_pos]).to_csv(real_pos_file, index=False)
                        
                        # 💡 V7.0 推播：買入確認通知
                        msg = f"✅ <b>進場確認：{row['sym']}</b>\n\n"
                        msg += f"買入張數：{qty} 張\n"
                        msg += f"進場均價：{row['price']} 台幣\n"
                        msg += f"初始停損：{row['stop_loss']} 台幣\n"
                        msg += f"單筆風險：{int((row['price'] - row['stop_loss']) * qty * 1000)} 台幣\n"
                        msg += "\n祝指揮官狩獵順利！🏹"
                        send_tg_msg(msg)
                        
                        st.rerun()
    else:
        st.info("目前無符合條件標的。")

with tab2:
    st.subheader("📍 部位動態管理 (自動移動停利與時間停損)")
    if not df_real.empty:
        updated_positions = []
        needs_update = False
        
        for i, r in df_real.iterrows():
            try:
                live_p = round(yf.Ticker(r['sym']).history(period="1d")['Close'].iloc[-1], 2)
            except:
                live_p = r['entry_p']
                
            risk_per_share = r['entry_p'] - r['hard_stop']
            target_1r = round(r['entry_p'] + risk_per_share, 2)
            
            # 階梯式移動停利
            new_trailing = round(live_p - (1.5 * r['atr']), 2)
            if new_trailing > r['trailing_stop']:
                r['trailing_stop'] = new_trailing
                needs_update = True
                
            entry_date_obj = datetime.strptime(r['entry_date'], "%Y-%m-%d")
            holding_days = (datetime.now() - entry_date_obj).days
            
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
                c1.write(f"### 📦 {r['sym']}\n成本: {r['entry_p']} 台幣 | 張數: {r['qty']}")
                
                unrealized_pnl = (live_p - r['entry_p']) / r['entry_p']
                pnl_color = "normal" if unrealized_pnl >= 0 else "inverse"
                c2.metric(f"即時現價 (持倉 {holding_days} 天)", live_p, f"{unrealized_pnl:.2%}", delta_color=pnl_color)
                c3.metric("移動停利線", r['trailing_stop'])
                
                if holding_days >= 5 and live_p < target_1r:
                    c4.warning("🐢 建議換股")
                elif live_p <= r['trailing_stop']:
                    c4.error("🚨 跌破防線！")
                elif live_p >= target_1r:
                    c4.success("🔥 達 1R 目標")

                if c4.button(f"🔴 依現價結算 {r['sym']}", key=f"sell_all_{i}"):
                    pnl = (live_p - r['entry_p']) * r['qty'] * 1000
                    realized_r = pnl / (risk_per_share * r['qty'] * 1000) if risk_per_share > 0 else 0
                    
                    new_hist = pd.DataFrame([{
                        'sym': r['sym'], 'type': r['type'], 'entry_date': r['entry_date'],
                        'exit_date': datetime.now().strftime("%Y-%m-%d"), 'entry_p': r['entry_p'],
                        'exit_p': live_p, 'qty': r['qty'], 'pnl': pnl, 'r_multiple': realized_r,
                        'target_p': target_1r, 'slippage': 0.005 
                    }])
                    pd.concat([df_hist, new_hist]).to_csv(history_file, index=False)
                    df_real = df_real.drop(i)
                    df_real.to_csv(real_pos_file, index=False)
                    
                    # 💡 V7.0 推播：結算戰果通知
                    pnl_str = f"+{int(pnl)}" if pnl > 0 else f"{int(pnl)}"
                    msg = f"🔴 <b>部位結算報告：{r['sym']}</b>\n\n"
                    msg += f"結算價格：{live_p} 台幣\n"
                    msg += f"實現損益：<b>{pnl_str} 台幣</b>\n"
                    msg += f"獲利倍數：{realized_r:.2f} R\n"
                    msg += f"持倉天數：{holding_days} 天\n"
                    msg += "\n資料已自動登錄至績效日誌！📊"
                    send_tg_msg(msg)
                    
                    st.rerun()
                    
            updated_positions.append(r)
            st.divider()
            
        if needs_update:
            pd.DataFrame(updated_positions).to_csv(real_pos_file, index=False)
    else:
        st.info("目前無持倉。")

with tab3:
    st.subheader("📈 系統績效")
    # ... (保持原有的績效與圖表代碼) ...
    if not df_hist.empty and len(df_hist) > 0:
        total_pnl = df_hist['pnl'].sum()
        st.metric("總實現損益", f"{int(total_pnl):,} 台幣")
        df_hist['cum_pnl'] = df_hist['pnl'].cumsum()
        st.line_chart(df_hist['cum_pnl'])