import pandas as pd
import yfinance as yf
import os
import re
import glob
from datetime import datetime

EXCEL_FILE = "trading_journal.xlsx"
INITIAL_BALANCE = 500.0
ALLOCATION_PER_TRADE = 100.0

def get_latest_scan_file():
    files = glob.glob("data/daily_scans/latest_optimized_scan.txt")
    return files[0] if files else None

def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty: return round(hist['Close'].iloc[-1], 2)
    except Exception: pass
    return None

def parse_signals(txt_path):
    buys, sells = {}, set()
    if not txt_path or not os.path.exists(txt_path): return buys, sells
    with open(txt_path, 'r', encoding='utf-8') as file: content = file.read()

    blocks = re.finditer(r"⭐ BUY #\d+: (\w+).*?Stop Loss: \$([\d.]+).*?Breakout: \$([\d.]+).*?Risk/Reward: ([\d.]+):1", content, re.DOTALL)
    for block in blocks:
        ticker, stop_loss, entry_price, rr_ratio = block.group(1), float(block.group(2)), float(block.group(3)), float(block.group(4))
        target_price = entry_price + ((entry_price - stop_loss) * rr_ratio)
        buys[ticker] = {'entry': entry_price, 'stop': stop_loss, 'target': round(target_price, 2)}
        
    sell_blocks = re.finditer(r"🚨 SELL #\d+: (\w+)", content, re.DOTALL)
    for block in sell_blocks: sells.add(block.group(1))
    return buys, sells

def update_journal():
    if os.path.exists(EXCEL_FILE): df = pd.read_excel(EXCEL_FILE)
    else: df = pd.DataFrame(columns=['Ticker', 'Date_Added', 'Entry_Price', 'Stop_Loss', 'Target_Price', 'Status', 'Shares', 'Invested', 'Current_Price', 'Close_Price', 'PnL_%', 'PnL_$'])
    
    for col in ['Shares', 'Invested', 'PnL_$', 'Stop_Loss', 'Target_Price']:
        if col not in df.columns: df[col] = 0.0
    df.fillna({'Shares': 0, 'Invested': 0.0, 'PnL_$': 0.0, 'Stop_Loss': 0.0, 'Target_Price': 0.0}, inplace=True)

    latest_txt = get_latest_scan_file()
    new_buys, current_sells = parse_signals(latest_txt)

    for ticker, data in new_buys.items():
        if ticker not in df['Ticker'].values:
            df = pd.concat([df, pd.DataFrame([{
                'Ticker': ticker, 'Date_Added': datetime.now().strftime("%Y-%m-%d"),
                'Entry_Price': data['entry'], 'Stop_Loss': data['stop'], 'Target_Price': data['target'],
                'Status': 'PENDING', 'Shares': 0, 'Invested': 0.0, 'Current_Price': None, 
                'Close_Price': None, 'PnL_%': None, 'PnL_$': 0.0
            }])], ignore_index=True)

    active_mask = df['Status'].isin(['PENDING', 'OPEN'])
    for index, row in df[active_mask].iterrows():
        ticker, entry_price = row['Ticker'], row['Entry_Price']
        stop_loss, target_price = row['Stop_Loss'], row['Target_Price']
        current_price = get_current_price(ticker)
        if current_price is None: continue

        df.at[index, 'Current_Price'] = current_price
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        if row['Status'] == 'PENDING':
            if current_price >= entry_price:
                risk_per_share = entry_price - stop_loss
                shares_to_buy = min(int((INITIAL_BALANCE * 0.02) // risk_per_share) if risk_per_share > 0 else 0, int(ALLOCATION_PER_TRADE // entry_price))
                if shares_to_buy > 0:
                    df.at[index, 'Status'] = 'OPEN'
                    df.at[index, 'Shares'] = shares_to_buy
                    df.at[index, 'Invested'] = round(shares_to_buy * entry_price, 2)

        elif row['Status'] == 'OPEN':
            df.at[index, 'PnL_%'] = round(pnl_pct, 2)
            df.at[index, 'PnL_$'] = round((row['Shares'] * current_price) - row['Invested'], 2)
            if current_price <= stop_loss or current_price >= target_price:
                df.at[index, 'Status'] = 'LOSS' if current_price <= stop_loss else 'WIN'
                df.at[index, 'Close_Price'] = current_price

    df.to_excel(EXCEL_FILE, index=False)
    print("Журнал обновлен в облаке!")
    
    # ВЫЗЫВАЕМ РАСЧЕТ БАЛАНСА
    calculate_balance(df)

def calculate_balance(df):
    cash = INITIAL_BALANCE
    for _, row in df.iterrows():
        if row['Status'] in ['OPEN', 'WIN', 'LOSS']:
            cash -= row['Invested']
        if row['Status'] in ['WIN', 'LOSS']:
            cash += (row['Invested'] + row['PnL_$'])
            
    open_value = sum(row['Shares'] * row['Current_Price'] for _, row in df[df['Status'] == 'OPEN'].iterrows() if pd.notna(row['Current_Price']))
    total_equity = cash + open_value
    total_profit = total_equity - INITIAL_BALANCE
    
    # Записываем в файл summary.txt, который потом прочитает GitHub Actions
    with open("summary.txt", "w", encoding="utf-8") as f:
        f.write(f"Старт: ${INITIAL_BALANCE:.2f} | Кэш: ${cash:.2f} | Активы: ${open_value:.2f} | Баланс: ${total_equity:.2f} | Профит: ${total_profit:.2f}")

if __name__ == "__main__":
    update_journal()
