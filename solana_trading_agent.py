import os
import time
import requests
import schedule
from flask import Flask
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Simple Top 10 Scanner"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8457965430:AAHERt3c9hX118RcVGLoxu1OZFyePK1c7dI')
CHAT_ID = os.environ.get('CHAT_ID', '-5232036612')
BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', 'demo')

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def get_and_send_top10():
    logger.info("\n" + "="*60)
    logger.info("Fetching top 10 coins by market cap...")
    logger.info("="*60)
    
    try:
        url = "https://public-api.birdeye.so/defi/tokenlist"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        params = {
            "sort_by": "mc",  # Sort by market cap
            "sort_type": "desc",
            "offset": 0,
            "limit": 10
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        logger.info(f"Birdeye API status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Error: {response.text}")
            send_telegram("❌ Failed to fetch data from Birdeye")
            return
        
        data = response.json()
        tokens = data.get('data', {}).get('tokens', [])
        
        logger.info(f"Got {len(tokens)} tokens")
        
        if not tokens:
            send_telegram("❌ No tokens returned from Birdeye")
            return
        
        # Filter out fake coins (must have real volume)
        real_coins = []
        for token in tokens:
            volume_24h = float(token.get('v24hUSD') or 0)
            if volume_24h > 1000:  # At least $1k volume to be real
                real_coins.append(token)
        
        logger.info(f"Found {len(real_coins)} coins with real volume")
        
        if not real_coins:
            send_telegram("❌ No coins with real volume found")
            return
        
        # Build message
        message = "📊 <b>TOP 10 REAL COINS BY MARKET CAP</b>\n"
        message += "<i>(Min $1k volume)</i>\n\n"
        
        for i, token in enumerate(real_coins[:10], 1):
            symbol = token.get('symbol', 'N/A')
            mc = float(token.get('mc') or 0)
            price = float(token.get('price') or 0)
            change_24h = float(token.get('v24hChangePercent') or 0)
            volume_24h = float(token.get('v24hUSD') or 0)
            
            message += f"<b>{i}. {symbol}</b>\n"
            message += f"   MC: ${mc:,.0f}\n"
            message += f"   Price: ${price:.6f}\n"
            message += f"   24h: {change_24h:+.1f}%\n"
            message += f"   Vol: ${volume_24h:,.0f}\n\n"
        
        logger.info("Sending to Telegram...")
        logger.info(f"\n{message}")
        
        if send_telegram(message):
            logger.info("✅ Sent successfully!")
        else:
            logger.error("❌ Failed to send")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())

def main():
    logger.info("="*60)
    logger.info("SIMPLE TOP 10 BY MARKET CAP SCANNER")
    logger.info("="*60)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask running")
    
    time.sleep(2)
    
    send_telegram("🤖 Simple Scanner Active!\n\nSending top 10 coins by market cap every 3 minutes")
    
    # First scan
    get_and_send_top10()
    
    # Schedule every 3 minutes
    schedule.every(3).minutes.do(get_and_send_top10)
    
    logger.info("\n✓ Scanner running...")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
