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
        
        logger.info("\n📋 Analyzing tokens with strict filters:")
        logger.info("   • Market Cap > $100k")
        logger.info("   • Liquidity > $50k")
        logger.info("   • Volume 24h > $20k")
        logger.info("   • Holder growth (24h)")
        logger.info("   • More buys than sells")
        
        for i, token in enumerate(tokens[:30]):  # Check more tokens since we have strict filters
            try:
                address = token.get('address', '')
                symbol = token.get('symbol', '')
                
                # Basic data
                price = float(token.get('price', 0))
                volume_24h = float(token.get('v24hUSD', 0))
                liquidity = float(token.get('liquidity', 0))
                market_cap = float(token.get('mc', 0))
                
                # Price changes
                price_change_24h = float(token.get('v24hChangePercent', 0))
                
                logger.info(f"\n{i+1}. {symbol}")
                logger.info(f"   MC: ${market_cap:.0f} | Liq: ${liquidity:.0f} | Vol: ${volume_24h:.0f}")
                
                # Skip if already notified
                if address in notified_coins:
                    logger.info(f"   ⏭ Already notified")
                    continue
                
                # FILTER 1: Basic requirements
                if market_cap < 100000:
                    logger.info(f"   ❌ Market cap too low (${market_cap:.0f})")
                    continue
                
                if liquidity < 50000:
                    logger.info(f"   ❌ Liquidity too low (${liquidity:.0f})")
                    continue
                
                if volume_24h < 20000:
                    logger.info(f"   ❌ Volume too low (${volume_24h:.0f})")
                    continue
                
                if price_change_24h <= 0:
                    logger.info(f"   ❌ Negative 24h ({price_change_24h:.1f}%)")
                    continue
                
                logger.info(f"   ✓ Passed basic filters")
                
                # FILTER 2: Get detailed token data from Birdeye
                logger.info(f"   📡 Fetching detailed data...")
                
                try:
                    detail_url = f"https://public-api.birdeye.so/defi/token_overview"
                    detail_params = {"address": address}
                    detail_response = requests.get(detail_url, headers=headers, params=detail_params, timeout=10)
                    
                    if detail_response.status_code == 200:
                        detail_data = detail_response.json().get('data', {})
                        
                        # Holder data
                        holder_count = detail_data.get('holder', 0)
                        holder_count_24h_ago = detail_data.get('holder24hAgo', holder_count)  # Fallback to current if not available
                        
                        # Trading data (buy vs sell pressure)
                        buy_24h = float(detail_data.get('buy24h', 0))
                        sell_24h = float(detail_data.get('sell24h', 0))
                        
                        logger.info(f"   Holders: {holder_count} (24h ago: {holder_count_24h_ago})")
                        logger.info(f"   Buy pressure: ${buy_24h:.0f} | Sell pressure: ${sell_24h:.0f}")
                        
                        # FILTER 3: Holder growth
                        holder_growth = holder_count - holder_count_24h_ago
                        if holder_growth <= 0:
                            logger.info(f"   ❌ No holder growth ({holder_growth})")
                            continue
                        
                        logger.info(f"   ✓ Holders increased by {holder_growth}")
                        
                        # FILTER 4: Buy vs Sell pressure
                        if sell_24h > 0:
                            buy_sell_ratio = buy_24h / sell_24h
                            if buy_sell_ratio <= 1.0:
                                logger.info(f"   ❌ More sells than buys (ratio: {buy_sell_ratio:.2f})")
                                continue
                            
                            logger.info(f"   ✓ Buy/Sell ratio: {buy_sell_ratio:.2f}")
                        else:
                            logger.info(f"   ✓ Only buys, no sells")
                            buy_sell_ratio = 999  # All buys
                        
                        # ALL FILTERS PASSED!
                        logger.info(f"   ✅✅ STRONG CANDIDATE!")
                        
                        candidates.append({
                            'symbol': symbol,
                            'address': address,
                            'price': price,
                            'price_change': price_change_24h,
                            'price_24h': price_change_24h,
                            'volume': volume_24h,
                            'liquidity': liquidity,
                            'market_cap': market_cap,
                            'holder_count': holder_count,
                            'holder_growth': holder_growth,
                            'buy_sell_ratio': buy_sell_ratio
                        })
                        
                    else:
                        logger.info(f"   ⚠ Could not fetch detailed data (status: {detail_response.status_code})")
                        continue
                        
                except Exception as e:
                    logger.info(f"   ⚠ Error fetching details: {e}")
                    continue
                    
            except Exception as e:
                logger.error(f"Error processing token: {e}")
                continue
        
        if not candidates:
            logger.info("\n❌ No coins passed all filters")
            return
        
        # Sort by buy/sell ratio (highest first)
        candidates.sort(key=lambda x: x['buy_sell_ratio'], reverse=True)
        best = candidates[0]
        
        logger.info(f"\n🎯 BEST SIGNAL: {best['symbol']}")
        logger.info(f"   Holder growth: +{best['holder_growth']}")
        logger.info(f"   Buy/Sell ratio: {best['buy_sell_ratio']:.2f}")
        
        # Dexscreener link
        dex_url = f"https://dexscreener.com/solana/{best['address']}"
        
        message = f"""
🚀 <b>HIGH-QUALITY SIGNAL</b>

<b>Token:</b> {best['symbol']}
<b>Price:</b> ${best['price']:.8f}

<b>📊 Performance:</b>
• 24h: +{best['price_24h']:.1f}%

<b>💰 Fundamentals:</b>
• Market Cap: ${best['market_cap']:.0f}
• Liquidity: ${best['liquidity']:.0f}
• Volume 24h: ${best['volume']:.0f}

<b>👥 Holder Metrics:</b>
• Total Holders: {best['holder_count']}
• 24h Growth: +{best['holder_growth']} holders

<b>📈 Buy Pressure:</b>
• Buy/Sell Ratio: {best['buy_sell_ratio']:.2f}x
{'• 🔥 Strong buying pressure!' if best['buy_sell_ratio'] > 2 else '• ✅ More buyers than sellers'}

<b>🔗 Chart:</b> {dex_url}

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
    
    send_telegram("🤖 Advanced Solana Scanner Active!\n\n✅ Strict Filters:\n• Market Cap > $100k\n• Liquidity > $50k\n• Volume > $20k\n• Holder growth (24h)\n• More buys than sells\n\n📊 Quality over quantity!")
    
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
