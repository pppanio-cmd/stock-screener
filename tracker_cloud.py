import pandas as pd
import yfinance as yf
import os
import re
import glob
import time
from datetime import datetime

EXCEL_FILE = "trading_journal_v4.xlsx"
INITIAL_BALANCE = 200.0
ALLOCATION_PERCENT = 0.5

def get_latest_scan_file():
    files = glob.glob("data/daily_scans/latest_optimized_scan.txt")
    if not files:
        return None
    file_path = files[0]
    # Защита: игнорируем файлы старше 2 дней
    if time.time() - os.path.getmtime(file_path) > 2 * 24 * 3600:
        print("⚠️ Файл сканера устарел. Игнорируем.")
        return None
    return file_path

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
    return buys, sells

def get_current_balance(df):
    if df is None or df.empty: return INITIAL_BALANCE, INITIAL_BALANCE
    cash = INITIAL_BALANCE
    for _, row in df.iterrows():
        if row['Status'] in ['OPEN', 'WIN', 'LOSS']: cash -= row['Invested']
        if row['Status'] in ['WIN', 'LOSS']: cash += (row['Invested'] + row['PnL_$'])
    open_value = sum(row['Shares'] * row['Current_Price'] for _, row in df[df['Status'] == 'OPEN'].iterrows() if pd.notna(row['Current_Price']))
    return cash + open_value, cash

def calculate_balance(df, events):
    total_equity, cash = get_current_balance(df)
    open_value = total_equity - cash
    total_profit = total_equity - INITIAL_BALANCE
    
    # Формируем красивый отчет
    report = f"💰 Баланс: ${total_equity:.2f} | Профит: ${total_profit:.2f}\n"
    report += f"💵 Кэш: ${cash:.2f} | Активы: ${open_value:.2f}\n\n"
    
    if events:
        report += "📋 ДЕЙСТВИЯ БОТА ЗА СЕГОДНЯ:\n"
        # Показываем последние 15 событий, чтобы не превысить лимит Телеграма
        for ev in events[-15:]:
            report += f"{ev}\n"
    else:
        report += "Нет новых сделок или сигналов."

    with open("summary.txt", "w", encoding="utf-8") as f:
        f.write(report)

def update_journal():
    df = pd.DataFrame(columns=['Ticker', 'Date_Added', 'Entry_Price', 'Stop_Loss', 'Target_Price', 'Status', 'Shares', 'Invested', 'Current_Price', 'Close_Price', 'PnL_%', 'PnL_$'])
    events = []  # <-- Список для логирования действий
    
    try:
        if os.path.exists(EXCEL_FILE): df = pd.read_excel(EXCEL_FILE)
        for col in ['Shares', 'Invested', 'PnL_$', 'Stop_Loss', 'Target_Price']:
            if col not in df.columns: df[col] = 0.0
        df.fillna({'Shares': 0, 'Invested': 0.0, 'PnL_$': 0.0, 'Stop_Loss': 0.0, 'Target_Price': 0.0}, inplace=True)

        latest_txt = get_latest_scan_file()
        new_buys, _ = parse_signals(latest_txt)

        if not new_buys:
            events.append("⏭ Нет свежих сигналов от сканера.")

        for ticker, data in new_buys.items():
            if ticker not in df['Ticker'].values:
                df = pd.concat([df, pd.DataFrame([{
                    'Ticker': ticker, 'Date_Added': datetime.now().strftime("%Y-%m-%d"),
                    'Entry_Price': data['entry'], 'Stop_Loss': data['stop'], 'Target_Price': data['target'],
                    'Status': 'PENDING', 'Shares': 0, 'Invested': 0.0, 'Current_Price': None, 'Close_Price': None, 'PnL_%': None, 'PnL_$': 0.0
                }])], ignore_index=True)

        active_mask = df['Status'].isin(['PENDING', 'OPEN'])
        for index, row in df[active_mask].iterrows():
            ticker, entry_price = row['Ticker'], row['Entry_Price']
            stop_loss, target_price = row['Stop_Loss'], row['Target_Price']
            current_price = get_current_price(ticker)
            
            if current_price is None: 
                continue

            df.at[index, 'Current_Price'] = current_price
            pnl_pct = ((current_price - entry_price) / entry_price) * 100

            if row['Status'] == 'PENDING':
                # Если цена пробила уровень, но не улетела выше +5%
                if entry_price <= current_price <= (entry_price * 1.05):
                    current_equity, current_cash = get_current_balance(df)
                    max_trade_value = current_equity * ALLOCATION_PERCENT
                    
                    alloc_shares = int(max_trade_value // current_price)
                    cash_shares = int(current_cash // current_price)
                    shares_to_buy = min(alloc_shares, cash_shares)
                    
                    if shares_to_buy > 0:
                        df.at[index, 'Status'] = 'OPEN'
                        df.at[index, 'Shares'] = shares_to_buy
                        df.at[index, 'Invested'] = round(shares_to_buy * current_price, 2)
                        events.append(f"🟢 КУПЛЕНО: {ticker} x{shares_to_buy} шт. по ${current_price} (на ${shares_to_buy * current_price:.2f})")
                    else:
                        events.append(f"⏭ ПРОПУЩЕНО: {ticker} - не хватает кэша (Нужно: ${max_trade_value:.0f}, Есть: ${current_cash:.0f})")
                else:
                    events.append(f"⏭ ПРОПУЩЕНО: {ticker} - цена уже улетела (Сигнал: ${entry_price}, Сейчас: ${current_price})")

            elif row['Status'] == 'OPEN':
                df.at[index, 'PnL_%'] = round(pnl_pct, 2)
                df.at[index, 'PnL_$'] = round((row['Shares'] * current_price) - row['Invested'], 2)
                
                # Проверка закрытия по стопу или тейку
                if current_price <= stop_loss:
                    df.at[index, 'Status'] = 'LOSS'
                    df.at[index, 'Close_Price'] = current_price
                    events.append(f"🔴 ЗАКРЫТО В МИНУС: {ticker} по ${current_price} (Убыток: ${df.at[index, 'PnL_$']:.2f})")
                elif current_price >= target_price:
                    df.at[index, 'Status'] = 'WIN'
                    df.at[index, 'Close_Price'] = current_price
                    events.append(f"💰 ЗАКРЫТО В ПЛЮС: {ticker} по ${current_price} (Профит: +${df.at[index, 'PnL_$']:.2f})")

        df.to_excel(EXCEL_FILE, index=False)
        
    except Exception as e:
        events.append(f"❌ ОШИБКА: {str(e)[:100]}")
        print(f"Ошибка: {e}")
    finally:
        calculate_balance(df, events)

if __name__ == "__main__":
    update_journal()
