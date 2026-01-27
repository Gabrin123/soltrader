import os
import time
import requests
import schedule
from datetime import datetime, timedelta
from flask import Flask
import threading
import json
from typing import Dict, List, Optional
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Solana Meme Coin Trading Agent is running!"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8457965430:AAHERt3c9hX118RcVGLoxu1OZFyePK1c7dI')
CHAT_ID = os.environ.get('CHAT_ID', '-5232036612')
WALLET_ADDRESS = os.environ.get('WALLET_ADDRESS', '8hZfubBEVqJGF73a4x9f8XFKgNRmHxdz9p81pScRzGmo')
SOLANA_PRIVATE_KEY = os.environ.get('SOLANA_PRIVATE_KEY', '')  # Will be added later

# Trading parameters
SOL_PER_TRADE = float(os.environ.get('SOL_PER_TRADE', '0.1'))
PROFIT_TARGET = 0.05  # 5%
HOLD_PERIOD_HOURS = 48
SCAN_INTERVAL_MINUTES = 15

# State management
last_notification_time = None
recently_notified_coins = []  # Track coins we've already sent
active_positions = {}  # {coin_address: {entry_price, entry_time, amount, ...}}
pending_approvals = {}  # {message_id: coin_data}

class SolanaScanner:
    """Scans for new Solana meme coins on pump.fun and bags.fm"""
    
    def __init__(self):
        self.last_scan = None
        
    def get_trending_coins(self) -> List[Dict]:
        """Fetch trending coins from Dexscreener"""
        try:
            # Dexscreener API for Solana new pairs (more likely to be meme coins)
            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                # Filter for new/trending meme coins
                trending = []
                for pair in pairs:
                    if pair.get('chainId') != 'solana':
                        continue
                    
                    base_symbol = pair.get('baseToken', {}).get('symbol', '')
                    quote_symbol = pair.get('quoteToken', {}).get('symbol', '')
                    
                    # Must be paired with SOL or USDC (not BE the SOL/USDC)
                    if quote_symbol not in ['SOL', 'USDC', 'WSOL']:
                        continue
                    
                    # Exclude major tokens and stablecoins
                    excluded = ['SOL', 'USDC', 'USDT', 'BONK', 'WIF', 'JUP', 'PYTH', 
                               'JTO', 'RNDR', 'HNT', 'WSOL', 'BSOL', 'MSOL', 'RAY',
                               'ORCA', 'SRM', 'FIDA', 'MNGO', 'SAMO']
                    
                    if base_symbol in excluded:
                        continue
                    
                    # Skip if symbol looks like a version token or wrapped token
                    if any(x in base_symbol for x in ['W', 'V2', 'V3', '_', 'OLD']):
                        if len(base_symbol) < 6:  # Unless it's a short meme name
                            continue
                    
                    # Basic filters for meme coins
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0))
                    volume_24h = float(pair.get('volume', {}).get('h24', 0))
                    price = float(pair.get('priceUsd', 0))
                    
                    # Look for actual meme coins:
                    # - Lower liquidity range (newer coins)
                    # - Decent volume
                    # - Very low price OR reasonable price with good volume
                    if (10000 < liquidity < 500000 and 
                        volume_24h > 5000 and 
                        (price < 0.01 or (price < 10 and volume_24h > 20000))):
                        
                        trending.append({
                            'address': pair.get('baseToken', {}).get('address'),
                            'symbol': base_symbol,
                            'name': pair.get('baseToken', {}).get('name'),
                            'price': price,
                            'volume_24h': volume_24h,
                            'liquidity': liquidity,
                            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
                            'dex_url': pair.get('url'),
                            'quote_token': quote_symbol
                        })
                
                logger.info(f"Found {len(trending)} trending meme coins")
                return trending
                
        except Exception as e:
            logger.error(f"Error fetching trending coins: {e}")
        
        return []

class TechnicalAnalyzer:
    """Analyzes charts using Money Line strategy"""
    
    def analyze_money_line(self, coin_data: Dict) -> Dict:
        """
        Simplified Money Line analysis based on Ivan on Tech strategy
        Returns: {is_bullish: bool, score: int, reasons: []}
        """
        try:
            address = coin_data['address']
            
            # Fetch detailed chart data from Dexscreener
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                return {'is_bullish': False, 'score': 0, 'reasons': ['No chart data']}
            
            data = response.json()
            pairs = data.get('pairs', [])
            
            if not pairs:
                return {'is_bullish': False, 'score': 0, 'reasons': ['No trading pairs']}
            
            # Use the most liquid pair
            pair = max(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
            
            score = 0
            reasons = []
            
            # 1. Price momentum (6h change - longer term)
            price_change_6h = float(pair.get('priceChange', {}).get('h6', 0))
            if price_change_6h > 0:
                score += 2
                reasons.append(f"Positive 6h momentum: +{price_change_6h:.2f}%")
            
            # 2. Strong 24h trend
            price_change_24h = float(pair.get('priceChange', {}).get('h24', 0))
            if price_change_24h > 5:  # At least 5% gain in 24h
                score += 1
                reasons.append(f"Strong 24h trend: +{price_change_24h:.2f}%")
            
            # 3. Volume increasing (compare 6h vs 24h average)
            volume_6h = float(pair.get('volume', {}).get('h6', 0))
            volume_24h = float(pair.get('volume', {}).get('h24', 0))
            if volume_6h > (volume_24h / 4) * 1.2:  # 6h volume > 1.2x avg
                score += 1
                reasons.append("Volume trending up")
            
            # 4. Not at recent high (avoid buying tops)
            price_change_1h = float(pair.get('priceChange', {}).get('h1', 0))
            if price_change_1h < 15:  # Not pumping heavily in last hour
                score += 1
                reasons.append("Not at immediate top")
            else:
                reasons.append(f"WARNING: Recent pump +{price_change_1h:.1f}% in 1h")
            
            # 5. Liquidity check
            liquidity = float(pair.get('liquidity', {}).get('usd', 0))
            if liquidity > 10000:
                score += 1
                reasons.append(f"Good liquidity: ${liquidity:.0f}")
            
            # Money Line is bullish if score >= 4
            is_bullish = score >= 4
            
            return {
                'is_bullish': is_bullish,
                'score': score,
                'reasons': reasons,
                'price': float(pair.get('priceUsd', 0)),
                'dex_url': pair.get('url')
            }
            
        except Exception as e:
            logger.error(f"Error in TA analysis: {e}")
            return {'is_bullish': False, 'score': 0, 'reasons': [f'Error: {str(e)}']}

class SocialAnalyzer:
    """Analyzes social sentiment on X and TikTok"""
    
    def check_twitter_sentiment(self, coin_symbol: str, coin_name: str) -> Dict:
        """
        Check Twitter/X sentiment via web scraping (no API needed)
        Returns: {is_positive: bool, score: int, summary: str}
        """
        try:
            # Use Google to search recent tweets
            query = f"{coin_symbol} OR {coin_name} solana site:twitter.com"
            search_url = f"https://www.google.com/search?q={query}&tbs=qdr:h"  # Last hour
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                content = response.text.lower()
                
                # Count bullish vs bearish keywords
                bullish_keywords = ['pump', 'moon', 'bullish', 'buy', 'gem', 'launch']
                bearish_keywords = ['scam', 'rug', 'dump', 'bearish', 'avoid']
                
                bullish_count = sum(content.count(word) for word in bullish_keywords)
                bearish_count = sum(content.count(word) for word in bearish_keywords)
                
                # Check for mentions
                mention_count = content.count('twitter.com')
                
                if mention_count > 5 and bullish_count > bearish_count * 2:
                    return {
                        'is_positive': True,
                        'score': 2,
                        'summary': f"{mention_count} mentions, bullish sentiment"
                    }
                elif mention_count > 10:
                    return {
                        'is_positive': True,
                        'score': 1,
                        'summary': f"{mention_count} mentions found"
                    }
            
            return {'is_positive': False, 'score': 0, 'summary': 'Low X activity'}
            
        except Exception as e:
            logger.error(f"Error checking Twitter: {e}")
            return {'is_positive': False, 'score': 0, 'summary': 'Error checking X'}
    
    def check_tiktok_sentiment(self, coin_symbol: str) -> Dict:
        """Check TikTok via web search"""
        try:
            query = f"{coin_symbol} solana crypto site:tiktok.com"
            search_url = f"https://www.google.com/search?q={query}&tbs=qdr:d"  # Last day
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(search_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                content = response.text
                tiktok_count = content.count('tiktok.com')
                
                if tiktok_count >= 3:
                    return {
                        'is_positive': True,
                        'score': 1,
                        'summary': f"{tiktok_count} TikTok videos found"
                    }
            
            return {'is_positive': False, 'score': 0, 'summary': 'No TikTok activity'}
            
        except Exception as e:
            logger.error(f"Error checking TikTok: {e}")
            return {'is_positive': False, 'score': 0, 'summary': 'Error checking TikTok'}

def send_telegram(message: str, reply_markup: Optional[Dict] = None) -> Optional[int]:
    """Send message to Telegram and return message_id"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            return response.json().get('result', {}).get('message_id')
        else:
            logger.error(f"Telegram error: {response.text}")
            
    except Exception as e:
        logger.error(f"Error sending Telegram: {e}")
    
    return None

def send_telegram_photo(photo_url: str, caption: str) -> bool:
    """Send photo to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        data = {
            'chat_id': CHAT_ID,
            'photo': photo_url,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        
        response = requests.post(url, data=data, timeout=15)
        
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Telegram photo error: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        return False

def check_telegram_responses():
    """Check for user responses to buy signals"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            updates = data.get('result', [])
            
            for update in updates:
                message = update.get('message', {})
                text = message.get('text', '').upper()
                
                if 'YES' in text or 'BUY' in text:
                    # User approved a trade
                    logger.info("User approved trade!")
                    # TODO: Execute buy (Phase 2)
                    
    except Exception as e:
        logger.error(f"Error checking responses: {e}")

def analyze_and_notify():
    """Main scanning and analysis function"""
    global last_notification_time
    
    # Check if we can send notification (max 1 per 3 minutes for testing)
    now = datetime.now()
    if last_notification_time and (now - last_notification_time).seconds < 180:
        logger.info("Waiting for next notification window (1 per 3 minutes)")
        return
    
    logger.info("="*60)
    logger.info("Starting scan cycle...")
    logger.info("="*60)
    
    # 1. Scan for coins
    scanner = SolanaScanner()
    coins = scanner.get_trending_coins()
    
    if not coins:
        logger.info("No trending coins found")
        return
    
    # 2. Analyze each coin
    ta_analyzer = TechnicalAnalyzer()
    social_analyzer = SocialAnalyzer()
    
    candidates = []
    
    for coin in coins[:10]:  # Check top 10
        logger.info(f"\nAnalyzing {coin['symbol']}...")
        
        # Skip if we already notified about this coin recently
        if coin['address'] in recently_notified_coins:
            logger.info(f"  ⏭ Already notified about this coin recently")
            continue
        
        # Technical analysis (Money Line)
        ta_result = ta_analyzer.analyze_money_line(coin)
        
        if not ta_result['is_bullish']:
            logger.info(f"  ❌ Not bullish (score: {ta_result['score']}/6)")
            continue
        
        logger.info(f"  ✓ Bullish Money Line (score: {ta_result['score']}/6)")
        
        # Social sentiment
        twitter_result = social_analyzer.check_twitter_sentiment(coin['symbol'], coin['name'])
        tiktok_result = social_analyzer.check_tiktok_sentiment(coin['symbol'])
        
        social_score = twitter_result['score'] + tiktok_result['score']
        
        # For testing: accept coins even without social signals
        # TODO: Re-enable social requirement after testing
        # if social_score < 1:
        #     logger.info(f"  ❌ Insufficient social signals")
        #     continue
        
        if social_score > 0:
            logger.info(f"  ✓ Social signals present (score: {social_score})")
        else:
            logger.info(f"  ⚠ No social signals (proceeding anyway for testing)")
        
        # This is a candidate!
        candidates.append({
            'coin': coin,
            'ta_result': ta_result,
            'twitter': twitter_result,
            'tiktok': tiktok_result,
            'total_score': ta_result['score'] + social_score
        })
    
    # 3. Pick best candidate
    if not candidates:
        logger.info("\n❌ No coins passed all filters")
        return
    
    # Sort by total score
    best = max(candidates, key=lambda x: x['total_score'])
    
    logger.info(f"\n🎯 BEST OPPORTUNITY: {best['coin']['symbol']}")
    logger.info(f"   Total score: {best['total_score']}")
    
    # 4. Send notification
    coin = best['coin']
    ta = best['ta_result']
    
    message = f"""
🚀 <b>BUY SIGNAL DETECTED</b>

<b>Coin:</b> {coin['symbol']} ({coin['name']})
<b>Address:</b> <code>{coin['address']}</code>
<b>Price:</b> ${ta['price']:.8f}
<b>24h Volume:</b> ${coin['volume_24h']:.0f}

<b>📊 Money Line Analysis (Score: {ta['score']}/6):</b>
{chr(10).join('• ' + r for r in ta['reasons'])}

<b>📱 Social Signals:</b>
• X: {best['twitter']['summary']}
• TikTok: {best['tiktok']['summary']}

<b>💰 Trade Setup:</b>
• Amount: {SOL_PER_TRADE} SOL
• Target: +5% (${ta['price'] * 1.05:.8f})
• Hold period: 48h if target not hit

<b>📈 View Chart:</b> {ta['dex_url']}

<b>Reply YES to execute trade or NO to skip</b>
"""
    
    msg_id = send_telegram(message.strip())
    
    if msg_id:
        last_notification_time = now
        pending_approvals[msg_id] = best
        recently_notified_coins.append(coin['address'])
        
        # Keep only last 20 coins in memory to avoid repeats
        if len(recently_notified_coins) > 20:
            recently_notified_coins.pop(0)
        
        logger.info("✓ Notification sent!")

def monitor_positions():
    """Monitor active positions for profit targets"""
    # TODO: Phase 2 - after we implement trading
    pass

def main():
    """Main bot loop"""
    logger.info("="*60)
    logger.info("SOLANA MEME COIN TRADING AGENT")
    logger.info("Strategy: Money Line + Social Sentiment")
    logger.info(f"Wallet: {WALLET_ADDRESS}")
    logger.info(f"Max notifications: 1 per 3 minutes (TESTING MODE)")
    logger.info("="*60)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask server started")
    
    time.sleep(2)
    
    # Send startup message
    send_telegram("🤖 Solana Meme Coin Agent is now active!\n\n📊 Scanning every 15 minutes\n💬 Max 1 signal per 3 minutes (testing mode)")
    
    # Run first scan immediately
    analyze_and_notify()
    
    # Schedule scans every 15 minutes
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(analyze_and_notify)
    
    # Check for responses every minute
    schedule.every(1).minutes.do(check_telegram_responses)
    
    # Monitor positions every 5 minutes
    schedule.every(5).minutes.do(monitor_positions)
    
    logger.info("\n✓ Agent is running...\n")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
