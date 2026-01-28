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
    return "Multi-Source Solana Scanner Running"

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

def get_pumpfun_coins():
    """Get new launches from pump.fun"""
    coins = []
    try:
        logger.info("📡 Checking pump.fun...")
        
        # Pump.fun new tokens API
        url = "https://frontend-api.pump.fun/coins?limit=50&offset=0&includeNsfw=false"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            for coin in data:
                try:
                    coins.append({
                        'source': 'pump.fun',
                        'address': coin.get('mint', ''),
                        'symbol': coin.get('symbol', ''),
                        'name': coin.get('name', ''),
                        'market_cap': float(coin.get('usd_market_cap', 0)),
                        'created_at': coin.get('created_timestamp', 0)
                    })
                except:
                    continue
            
            logger.info(f"   Found {len(coins)} pump.fun coins")
        else:
            logger.warning(f"   pump.fun returned {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error fetching pump.fun: {e}")
    
    return coins

def get_dexscreener_data(address):
    """Get detailed data from Dexscreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            pairs = data.get('pairs', [])
            
            if pairs:
                # Get the most liquid pair
                pair = max(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
                
                return {
                    'price': float(pair.get('priceUsd', 0)),
                    'liquidity': float(pair.get('liquidity', {}).get('usd', 0)),
                    'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                    'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                    'dex_url': pair.get('url', '')
                }
    except:
        pass
    
    return None

def get_birdeye_details(address):
    """Get holder and trading data from Birdeye"""
    try:
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        url = f"https://public-api.birdeye.so/defi/token_overview"
        params = {"address": address}
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            
            return {
                'holder_count': data.get('holder', 0),
                'holder_24h_ago': data.get('holder24hAgo', 0),
                'buy_24h': float(data.get('buy24h', 0)),
                'sell_24h': float(data.get('sell24h', 0))
            }
    except:
        pass
    
    return None

def analyze_coin(coin_info):
    """Comprehensive analysis of a coin"""
    
    address = coin_info['address']
    symbol = coin_info['symbol']
    source = coin_info.get('source', 'unknown')
    is_pumpfun = (source == 'pump.fun')
    
    logger.info(f"\n🔍 Analyzing {symbol} (from {source})")
    
    # Skip if already notified
    if address in notified_coins:
        logger.info(f"   ⏭ Already notified")
        return None
    
    # Get Dexscreener data
    dex_data = get_dexscreener_data(address)
    if not dex_data:
        logger.info(f"   ❌ No Dexscreener data")
        return None
    
    logger.info(f"   Price: ${dex_data['price']:.8f}")
    logger.info(f"   Liquidity: ${dex_data['liquidity']:.0f}")
    logger.info(f"   Volume 24h: ${dex_data['volume_24h']:.0f}")
    logger.info(f"   24h Change: {dex_data['price_change_24h']:.1f}%")
    
    # RELAXED FILTERS FOR PUMP.FUN (new launches)
    if is_pumpfun:
        logger.info(f"   🎯 pump.fun coin - using relaxed filters")
        
        # Much lower thresholds for new launches
        if dex_data['liquidity'] < 5000:
            logger.info(f"   ❌ Liquidity too low (<$5k)")
            return None
        
        if dex_data['volume_24h'] < 2000:
            logger.info(f"   ❌ Volume too low (<$2k)")
            return None
        
        # For pump.fun, just need positive momentum
        if dex_data['price_change_24h'] < 0:
            logger.info(f"   ❌ Negative price action")
            return None
        
        logger.info(f"   ✅ Passed pump.fun filters!")
        
        market_cap = coin_info.get('market_cap', 0)
        if market_cap == 0:
            market_cap = dex_data['liquidity'] * 2
        
        # Try to get Birdeye data but don't require it
        birdeye_data = get_birdeye_details(address)
        
        if birdeye_data and birdeye_data['holder_count'] > 0:
            holder_count = birdeye_data['holder_count']
            holder_24h_ago = birdeye_data['holder_24h_ago']
            buy_24h = birdeye_data['buy_24h']
            sell_24h = birdeye_data['sell_24h']
            holder_growth = holder_count - holder_24h_ago
            
            buy_sell_ratio = buy_24h / sell_24h if sell_24h > 0 else 999
            
            logger.info(f"   📊 Holders: {holder_count} (growth: {holder_growth})")
        else:
            logger.info(f"   ℹ️ No holder data yet (new coin)")
            holder_count = 0
            holder_growth = 0
            buy_sell_ratio = 0
        
        return {
            'symbol': symbol,
            'address': address,
            'source': source,
            'price': dex_data['price'],
            'liquidity': dex_data['liquidity'],
            'volume_24h': dex_data['volume_24h'],
            'price_change_24h': dex_data['price_change_24h'],
            'market_cap': market_cap,
            'holder_count': holder_count,
            'holder_growth': holder_growth,
            'buy_sell_ratio': buy_sell_ratio,
            'dex_url': dex_data['dex_url']
        }
    
    # STRICT FILTERS FOR BIRDEYE (established coins)
    else:
        logger.info(f"   📊 Birdeye coin - using strict filters")
        
        if dex_data['liquidity'] < 50000:
            logger.info(f"   ❌ Liquidity too low (<$50k)")
            return None
        
        if dex_data['volume_24h'] < 20000:
            logger.info(f"   ❌ Volume too low (<$20k)")
            return None
        
        market_cap = coin_info.get('market_cap', 0)
        if market_cap == 0 and dex_data['price'] > 0:
            market_cap = dex_data['liquidity'] * 2
        
        if market_cap < 100000:
            logger.info(f"   ❌ Market cap too low (${market_cap:.0f})")
            return None
        
        logger.info(f"   ✓ Passed basic filters")
        
        # Get Birdeye data
        logger.info(f"   📡 Checking Birdeye...")
        birdeye_data = get_birdeye_details(address)
        
        if birdeye_data:
            holder_count = birdeye_data['holder_count']
            holder_24h_ago = birdeye_data['holder_24h_ago']
            buy_24h = birdeye_data['buy_24h']
            sell_24h = birdeye_data['sell_24h']
            
            holder_growth = holder_count - holder_24h_ago
            
            logger.info(f"   Holders: {holder_count} (growth: {holder_growth})")
            logger.info(f"   Buy: ${buy_24h:.0f} | Sell: ${sell_24h:.0f}")
            
            if holder_growth <= 0:
                logger.info(f"   ❌ No holder growth")
                return None
            
            if sell_24h > 0:
                buy_sell_ratio = buy_24h / sell_24h
                if buy_sell_ratio <= 1.0:
                    logger.info(f"   ❌ More sells than buys ({buy_sell_ratio:.2f})")
                    return None
            else:
                buy_sell_ratio = 999
            
            logger.info(f"   ✅✅ ALL FILTERS PASSED!")
            
            return {
                'symbol': symbol,
                'address': address,
                'source': source,
                'price': dex_data['price'],
                'liquidity': dex_data['liquidity'],
                'volume_24h': dex_data['volume_24h'],
                'price_change_24h': dex_data['price_change_24h'],
                'market_cap': market_cap,
                'holder_count': holder_count,
                'holder_growth': holder_growth,
                'buy_sell_ratio': buy_sell_ratio,
                'dex_url': dex_data['dex_url']
            }
        else:
            logger.info(f"   ⚠ No Birdeye data")
            return None
    
    return None

def scan_and_notify():
    global last_notification_time
    
    now = datetime.now()
    if last_notification_time and (now - last_notification_time).seconds < 180:
        logger.info("⏸ Waiting for next notification window")
        return
    
    logger.info("\n" + "="*70)
    logger.info("🔍 MULTI-SOURCE SCAN")
    logger.info("="*70)
    
    all_candidates = []
    
    # SOURCE 1: Pump.fun
    pumpfun_coins = get_pumpfun_coins()
    for coin in pumpfun_coins[:20]:  # Check top 20
        result = analyze_coin(coin)
        if result:
            all_candidates.append(result)
    
    # SOURCE 2: Birdeye trending (existing)
    try:
        logger.info("\n📡 Checking Birdeye trending...")
        url = "https://public-api.birdeye.so/defi/tokenlist"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        params = {"sort_by": "v24hChangePercent", "sort_type": "desc", "offset": 0, "limit": 20}
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            tokens = data.get('data', {}).get('tokens', [])
            logger.info(f"   Found {len(tokens)} Birdeye tokens")
            
            for token in tokens[:10]:
                coin_info = {
                    'source': 'Birdeye',
                    'address': token.get('address', ''),
                    'symbol': token.get('symbol', ''),
                    'name': token.get('name', ''),
                    'market_cap': float(token.get('mc', 0))
                }
                
                result = analyze_coin(coin_info)
                if result:
                    all_candidates.append(result)
    except Exception as e:
        logger.error(f"Error with Birdeye: {e}")
    
    # Pick best candidate
    if not all_candidates:
        logger.info("\n❌ No coins passed all filters")
        return
    
    # Sort by buy/sell ratio (or price change if no ratio)
    all_candidates.sort(key=lambda x: x.get('buy_sell_ratio', 0) or x.get('price_change_24h', 0), reverse=True)
    best = all_candidates[0]
    
    logger.info(f"\n🎯 BEST SIGNAL: {best['symbol']} (from {best['source']})")
    
    # Build message
    holder_info = ""
    if best['holder_growth'] > 0:
        holder_info = f"""
<b>👥 Holder Metrics:</b>
• Total Holders: {best['holder_count']}
• 24h Growth: +{best['holder_growth']} holders
"""
    
    buy_pressure_info = ""
    if best['buy_sell_ratio'] > 0:
        buy_pressure_info = f"""
<b>📈 Buy Pressure:</b>
• Buy/Sell Ratio: {best['buy_sell_ratio']:.2f}x
{'• 🔥 Strong buying pressure!' if best['buy_sell_ratio'] > 2 else '• ✅ More buyers than sellers'}
"""
    
    message = f"""
🚀 <b>HIGH-QUALITY SIGNAL</b>
📍 Source: {best['source']}

<b>Token:</b> {best['symbol']}
<b>Price:</b> ${best['price']:.8f}

<b>📊 Performance:</b>
• 24h: +{best['price_change_24h']:.1f}%

<b>💰 Fundamentals:</b>
• Market Cap: ${best['market_cap']:.0f}
• Liquidity: ${best['liquidity']:.0f}
• Volume 24h: ${best['volume_24h']:.0f}
{holder_info}{buy_pressure_info}
<b>🔗 Chart:</b> {best['dex_url']}

<b>Address:</b> <code>{best['address']}</code>

<i>Reply YES to buy or NO to skip</i>
"""
    
    if send_telegram(message.strip()):
        last_notification_time = now
        notified_coins.append(best['address'])
        
        if len(notified_coins) > 30:
            notified_coins.pop(0)
        
        logger.info("✅ Notification sent!")

def main():
    logger.info("="*70)
    logger.info("MULTI-SOURCE SOLANA SCANNER")
    logger.info("Sources: pump.fun + Birdeye")
    logger.info("="*70)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask running")
    
    time.sleep(2)
    
    send_telegram("🤖 Multi-Source Scanner Active!\n\n📡 Scanning:\n• pump.fun (new launches)\n• Birdeye (trending)\n\n✅ Strict quality filters active")
    
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
