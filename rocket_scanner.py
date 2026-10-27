import yfinance as yf
from yfinance import EquityQuery
import pandas as pd
from datetime import datetime

def scan_rockets():
    print("🚀 Сканируем рынок на наличие 'ракет'...")
    # Ищем акции: цена до $20, объем от 1 млн, сегодняшний рост > 10%
    q = EquityQuery('and', [
        EquityQuery('lt', ['intradayprice', 20]),
        EquityQuery('gt', ['dayvolume', 1000000]),
        EquityQuery('gt', ['regularMarketChangePercent', 10.0]), 
        EquityQuery('is-in', ['exchange', 'NMS', 'NYQ', 'ASE'])
    ])
    
    try:
        r = yf.screen(q, size=10, sortField='regularMarketChangePercent', sortAsc=False)
    except Exception as e:
        print(f"Ошибка сканера: {e}")
        return

    if not r or 'quotes' not in r:
        print("Ракет сегодня нет.")
        return

    output = f"📊 РАКЕТНЫЙ СКАНЕР от {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    for i, quote in enumerate(r['quotes'], 1):
        ticker = quote.get('symbol')
        price = quote.get('regularMarketPrice')
        change = quote.get('regularMarketChangePercent')
        
        if not price or not ticker: continue
        
        # Для ракет ставим стоп в 7%, а тейк в 20%
        stop = round(price * 0.93, 2)
        target = round(price * 1.20, 2)
        
        output += f"⭐ BUY #{i}: {ticker}\n"
        output += f"Stop Loss: ${stop}\n"
        output += f"Breakout: ${price}\n"
        output += f"Risk/Reward: 2.8:1\n" 
        output += f"(Текущий рост: {change:.1f}%)\n\n"

    with open("data/daily_scans/latest_rocket_scan.txt", "w", encoding="utf-8") as f:
        f.write(output)
    print(f"✅ Найдено ракет: {len(r['quotes'])}. Файл сохранен!")

if __name__ == "__main__":
    import os
    os.makedirs("data/daily_scans", exist_ok=True)
    scan_rockets()
