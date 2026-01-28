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
    return "Birdeye Solana Scanner Running"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8457965430:AAHERt3c9hX118RcVGLoxu1OZFyePK1c7dI')
CHAT_ID = os.environ.get('CHAT_ID', '-5232036612')
BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', 'demo')

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
    logger.info("🔍 SCANNING WITH BIRDEYE API...")
    logger.info("="*70)
    
    try:
        # Get trending tokens from Birdeye
        url = "https://public-api.birdeye.so/defi/tokenlist"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        params = {
            "sort_by": "v24hChangePercent",
            "sort_type": "desc",
            "offset": 0,
            "limit": 50
        }
        
        logger.info(f"📡 Calling Birdeye API...")
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        logger.info(f"📊 Birdeye returned status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"❌ Birdeye error: {response.text}")
            return
        
        data = response.json()
        tokens = data.get('data', {}).get('tokens', [])
        
        logger.info(f"✅ Got {len(tokens)} tokens from Birdeye")
        
        if not tokens:
            logger.warning("⚠️ No tokens returned")
            return
        
        candidates = []
        
        logger.info("\n📋 Analyzing tokens:")
        
        for i, token in enumerate(tokens[:20]):  # Check first 20
            try:
                address = token.get('address', '')
                symbol = token.get('symbol', '')
                
                # Get price changes (Birdeye only has 24h reliably)
                price_change_24h = float(token.get('v24hChangePercent', 0))
                price_change_1h = float(token.get('v1hChangePercent', 0))
                
                # Get other data
                price = float(token.get('price', 0))
                volume_24h = float(token.get('v24hUSD', 0))
                liquidity = float(token.get('liquidity', 0))
                
                # Log each token to see what we're getting
                logger.info(f"\n{i+1}. {symbol}")
                logger.info(f"   1h: {price_change_1h:.1f}% | 24h: {price_change_24h:.1f}%")
                logger.info(f"   Vol: ${volume_24h:.0f} | Liq: ${liquidity:.0f}")
                
                # Skip if already notified
                if address in notified_coins:
                    logger.info(f"   ⏭ Already notified")
                    continue
                
                # SIMPLE RULE: Positive 24h movement + minimum $10k volume
                if price_change_24h > 0 and volume_24h > 10000:
                    logger.info(f"   ✅ CANDIDATE!")
                    
                    candidates.append({
                        'symbol': symbol,
                        'address': address,
                        'price': price,
                        'price_change': price_change_24h,
                        'price_1h': price_change_1h,
                        'price_24h': price_change_24h,
                        'volume': volume_24h,
                        'liquidity': liquidity
                    })
                else:
                    logger.info(f"   ❌ Negative or low volume (<$10k)")
                    
            except Exception as e:
                logger.error(f"Error processing token: {e}")
                continue
        
        if not candidates:
            logger.info("\n❌ No coins with positive movement found")
            return
        
        # Sort by price change
        candidates.sort(key=lambda x: x['price_change'], reverse=True)
        best = candidates[0]
        
        logger.info(f"\n🎯 SENDING: {best['symbol']} (+{best['price_change']:.1f}%)")
        
        # Dexscreener link
        dex_url = f"https://dexscreener.com/solana/{best['address']}"
        
        message = f"""
🚀 <b>MEME COIN SIGNAL</b>

<b>Token:</b> {best['symbol']}
<b>Price:</b> ${best['price']:.8f}

<b>Performance:</b>
• Recent: +{best['price_change']:.1f}%
• 24h: +{best['price_24h']:.1f}%

<b>Stats:</b>
• Volume 24h: ${best['volume']:.0f}
• Liquidity: ${best['liquidity']:.0f}

<b>📈 Chart:</b> {dex_url}

<b>Address:</b> <code>{best['address']}</code>

<i>Reply YES to buy or NO to skip</i>
"""
        
        if send_telegram(message.strip()):
            last_notification_time = now
            notified_coins.append(best['address'])
            
            if len(notified_coins) > 30:
                notified_coins.pop(0)
            
            logger.info("✅ Notification sent!")
        
    except Exception as e:
        logger.error(f"❌ Error in scan: {e}")
        import traceback
        logger.error(traceback.format_exc())

def main():
    logger.info("="*70)
    logger.info("BIRDEYE SOLANA MEME COIN SCANNER")
    logger.info(f"API Key: {BIRDEYE_API_KEY[:10]}...")
    logger.info("="*70)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask running")
    
    time.sleep(2)
    
    send_telegram("🤖 Birdeye Scanner Active!\n\nLooking for coins with positive 6h movement\n📊 Updates every 3 minutes")
    
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
