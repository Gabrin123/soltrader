import os
import time
import requests
import schedule
from datetime import datetime
from flask import Flask
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Simple Solana Scanner Running"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8457965430:AAHERt3c9hX118RcVGLoxu1OZFyePK1c7dI')
CHAT_ID = os.environ.get('CHAT_ID', '-5232036612')

last_notification_time = None
notified_coins = []

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': False}
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def scan_and_notify():
    global last_notification_time
    
    now = datetime.now()
    if last_notification_time and (now - last_notification_time).seconds < 180:
        logger.info("⏸ Waiting for next notification window (3 min cooldown)")
        return
    
    logger.info("\n" + "="*70)
    logger.info("🔍 SCANNING FOR MEME COINS...")
    logger.info("="*70)
    
    try:
        # Get Solana pairs from Dexscreener
        url = "https://api.dexscreener.com/latest/dex/pairs/solana"
        response = requests.get(url, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"❌ Dexscreener returned {response.status_code}")
            return
        
        data = response.json()
        pairs = data.get('pairs', [])
        
        logger.info(f"📊 Got {len(pairs)} pairs from Dexscreener")
        
        candidates = []
        
        for pair in pairs[:50]:  # Check first 50
            try:
                # Basic info
                symbol = pair.get('baseToken', {}).get('symbol', '')
                address = pair.get('baseToken', {}).get('address', '')
                quote = pair.get('quoteToken', {}).get('symbol', '')
                
                # Skip if not paired with SOL/USDC
                if quote not in ['SOL', 'USDC', 'WSOL']:
                    continue
                
                # Skip major tokens
                if symbol in ['SOL', 'USDC', 'USDT', 'WSOL']:
                    continue
                
                # Skip if already notified
                if address in notified_coins:
                    continue
                
                # Get price changes
                price_6h = float(pair.get('priceChange', {}).get('h6', 0))
                price_24h = float(pair.get('priceChange', {}).get('h24', 0))
                
                # Get other data
                price = float(pair.get('priceUsd', 0))
                volume_24h = float(pair.get('volume', {}).get('h24', 0))
                liquidity = float(pair.get('liquidity', {}).get('usd', 0))
                url_dex = pair.get('url', '')
                
                # SIMPLE RULE: Just positive 6h price change + minimum volume/liquidity
                if price_6h > 0 and volume_24h > 1000 and liquidity > 2000:
                    logger.info(f"\n✅ FOUND: {symbol}")
                    logger.info(f"   6h: +{price_6h:.1f}% | 24h: +{price_24h:.1f}%")
                    logger.info(f"   Volume: ${volume_24h:.0f} | Liq: ${liquidity:.0f}")
                    
                    candidates.append({
                        'symbol': symbol,
                        'address': address,
                        'price': price,
                        'price_6h': price_6h,
                        'price_24h': price_24h,
                        'volume': volume_24h,
                        'liquidity': liquidity,
                        'url': url_dex
                    })
                    
            except Exception as e:
                continue
        
        if not candidates:
            logger.info("\n❌ No coins with positive 6h movement found")
            return
        
        # Sort by 6h performance
        candidates.sort(key=lambda x: x['price_6h'], reverse=True)
        best = candidates[0]
        
        logger.info(f"\n🎯 SENDING: {best['symbol']} (+{best['price_6h']:.1f}% in 6h)")
        
        message = f"""
🚀 <b>MEME COIN SIGNAL</b>

<b>Token:</b> {best['symbol']}
<b>Price:</b> ${best['price']:.8f}

<b>Performance:</b>
• 6h: +{best['price_6h']:.1f}%
• 24h: +{best['price_24h']:.1f}%

<b>Stats:</b>
• Volume 24h: ${best['volume']:.0f}
• Liquidity: ${best['liquidity']:.0f}

<b>📈 Chart:</b> {best['url']}

<b>Address:</b> <code>{best['address']}</code>

<i>Reply YES to buy or NO to skip</i>
"""
        
        if send_telegram(message.strip()):
            last_notification_time = now
            notified_coins.append(best['address'])
            
            # Keep list manageable
            if len(notified_coins) > 30:
                notified_coins.pop(0)
            
            logger.info("✅ Notification sent!")
        
    except Exception as e:
        logger.error(f"❌ Error in scan: {e}")

def main():
    logger.info("="*70)
    logger.info("SIMPLE SOLANA MEME COIN SCANNER")
    logger.info("Rule: Any coin with positive 6h movement")
    logger.info("="*70)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask running")
    
    time.sleep(2)
    
    send_telegram("🤖 Simple Scanner Active!\n\nLooking for coins with positive 6h movement\n📊 Updates every 3 minutes")
    
    # First scan
    scan_and_notify()
    
    # Schedule every 3 minutes
    schedule.every(3).minutes.do(scan_and_notify)
    
    logger.info("\n✓ Scanner running...\n")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
