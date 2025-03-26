import os
import ccxt
import time
import json
import sys
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Retrieve credentials from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Initialize Kraken connection
kraken = ccxt.kraken()

# Define constants
TRADING_PAIRS = 'SOL/USDT'
TRADE_AMOUNT = 0.01
TAKE_PROFIT_INITIAL = 0.02
STOP_LOSS_BUFFER = 0.01
COOLDOWN_PERIOD = 15 * 60
TRADE_LOG_FILE = 'trade_log.json'
SUMMARY_FILE = 'monthly_profit_loss.json'

# Track bot start time
start_time = datetime.now()

# Ensure log file exists
if not os.path.exists(TRADE_LOG_FILE):
    with open(TRADE_LOG_FILE, 'w') as f:
        json.dump([], f)

def send_telegram_message(message):
    """Send a message to the Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        print("Telegram message sent:", message)
    except requests.exceptions.RequestException as e:
        print("Failed to send message:", e)

def fetch_candles():
    """Fetch the last 7 minutes of 1-minute candles."""
    for _ in range(3):
        try:
            return kraken.fetch_ohlcv(TRADING_PAIRS, timeframe='1m', limit=7)
        except Exception as e:
            print("Error fetching candles:", e)
        time.sleep(5)
    return []

def get_high_low(candles):
    """Get high and low from last 7 candles."""
    if not candles:
        return None, None
    high = max(c[2] for c in candles)
    low = min(c[3] for c in candles)
    return high, low

def get_current_price():
    """Fetch the current market price."""
    for _ in range(3):
        try:
            return kraken.fetch_ticker(TRADING_PAIRS)['last']
        except Exception as e:
            print("Error fetching price:", e)
        time.sleep(5)
    return None

def log_trade(entry_price, exit_price, trade_type, reason):
    """Log trade details and calculate profit/loss."""
    trade_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    profit_loss = round((exit_price - entry_price) * TRADE_AMOUNT, 4) if trade_type == 'LONG' else round((entry_price - exit_price) * TRADE_AMOUNT, 4)
    
    trade_data = {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "trade_type": trade_type,
        "profit_loss": profit_loss,
        "time": trade_time,
        "reason": reason
    }

    # Append trade data to trade log
    with open(TRADE_LOG_FILE, 'r+') as file:
        trades = json.load(file)
        trades.append(trade_data)
        file.seek(0)
        json.dump(trades, file, indent=4)

def trailing_stop_loss(entry_price, stop_loss, trade_type):
    """Implement trailing stop loss strategy."""
    while True:
        time.sleep(10)
        current_price = get_current_price()
        if current_price is None:
            continue

        if trade_type == 'LONG':
            if current_price > entry_price * 1.01:
                stop_loss = max(stop_loss, entry_price * 1.005)
            if current_price > entry_price * 1.02:
                stop_loss = max(stop_loss, entry_price * 1.01)
            if current_price < stop_loss:
                log_trade(entry_price, current_price, 'LONG', "Trailing Stop Loss Hit")
                send_telegram_message(f"Trailing Stop Loss Hit - Exiting LONG at {current_price}")
                break

        elif trade_type == 'SHORT':
            if current_price < entry_price * 0.99:
                stop_loss = min(stop_loss, entry_price * 0.995)
            if current_price < entry_price * 0.98:
                stop_loss = min(stop_loss, entry_price * 0.99)
            if current_price > stop_loss:
                log_trade(entry_price, current_price, 'SHORT', "Trailing Stop Loss Hit")
                send_telegram_message(f"Trailing Stop Loss Hit - Exiting SHORT at {current_price}")
                break

def monitor_market():
    """Monitor the market for trade signals based on a 7-minute high/low breakout strategy."""
    candles = fetch_candles()
    high, low = get_high_low(candles)
    if high is None or low is None:
        print("High/Low values are None. Skipping monitoring.")
        return

    print(f"Monitoring market. 7-minute range: High = {high}, Low = {low}")
    send_telegram_message(f"Monitoring market. 7-minute range: High = {high}, Low = {low}")

    entry_signal = None
    while True:
        time.sleep(10)
        current_price = get_current_price()
        if current_price is None:
            continue

        print(f'Current Price: {current_price}')
        if entry_signal is None:
            if current_price > high:
                entry_signal = 'LONG'
                send_telegram_message(f"Signal generated: LONG above {high}")
            elif current_price < low:
                entry_signal = 'SHORT'
                send_telegram_message(f"Signal generated: SHORT below {low}")

        if entry_signal:
            if entry_signal == 'LONG' and low < current_price < high:
                print("Entering LONG trade on retracement at", current_price)
                send_telegram_message(f"Entering LONG trade on retracement at {current_price}")
                trailing_stop_loss(current_price, low, 'LONG')
                break
            elif entry_signal == 'LONG' and current_price > high:
                print("Chasing LONG trade at", current_price)
                send_telegram_message(f"Chasing LONG trade at {current_price}")
                trailing_stop_loss(current_price, low, 'LONG')
                break
            elif entry_signal == 'SHORT' and low < current_price < high:
                print("Entering SHORT trade on retracement at", current_price)
                send_telegram_message(f"Entering SHORT trade on retracement at {current_price}")
                trailing_stop_loss(current_price, high, 'SHORT')
                break
            elif entry_signal == 'SHORT' and current_price < low:
                print("Chasing SHORT trade at", current_price)
                send_telegram_message(f"Chasing SHORT trade at {current_price}")
                trailing_stop_loss(current_price, high, 'SHORT')
                break

def generate_summary():
    """Create a 30-day profit/loss summary and reset logs."""
    with open(TRADE_LOG_FILE, 'r') as file:
        trades = json.load(file)

    total_profit_loss = sum(t["profit_loss"] for t in trades)

    summary_data = {
        "start_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
        "end_date": datetime.now().strftime("%Y-%m-%d"),
        "total_profit_loss": total_profit_loss,
        "trade_count": len(trades),
        "trades": trades
    }

    # Save summary permanently
    with open(SUMMARY_FILE, 'a') as file:
        json.dump(summary_data, file, indent=4)
        file.write("\n\n")  # Separate entries

    # Reset trade log for next cycle
    with open(TRADE_LOG_FILE, 'w') as file:
        json.dump([], file)

    send_telegram_message(f"30-day report: Total P/L = {total_profit_loss}. Logs reset.")

def main():
    global start_time  # Declare global at the beginning
    send_telegram_message("Starting trading bot...")

    while True:
        try:
            if datetime.now() >= start_time + timedelta(days=30):
                generate_summary()
                start_time = datetime.now()  # Reset start time for next 30 days

            monitor_market()
            time.sleep(COOLDOWN_PERIOD)
        except Exception as e:
            send_telegram_message(f"Bot crashed: {e}. Restarting...")
            time.sleep(10)

print(f"Telegram Token: {TELEGRAM_TOKEN}")
if __name__ == "__main__":
    main()
