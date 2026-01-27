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
    return "Solana Meme Coin Trading Agent V2 is running!"

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
SOLANA_PRIVATE_KEY = os.environ.get('SOLANA_PRIVATE_KEY', '')

# Birdeye API (free tier)
BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY', 'demo')  # Get free key from birdeye.so

# Trading parameters
SOL_PER_TRADE = float(os.environ.get('SOL_PER_TRADE', '0.1'))
PROFIT_TARGET = 0.05
HOLD_PERIOD_HOURS = 48
SCAN_INTERVAL_MINUTES = 15

# State management
last_notification_time = None
recently_notified_coins = []
active_positions = {}
pending_approvals = {}

class SolanaScanner:
    """Scans for new Solana meme coins with on-chain analysis"""
    
    def __init__(self):
        self.last_scan = None
        
    def get_trending_coins(self) -> List[Dict]:
        """Fetch trending coins from Dexscreener"""
        try:
            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                logger.info(f"Dexscreener returned {len(pairs)} total pairs")
                
                trending = []
                
                for pair in pairs[:100]:
                    if pair.get('chainId') != 'solana':
                        continue
                    
                    base_symbol = pair.get('baseToken', {}).get('symbol', '')
                    quote_symbol = pair.get('quoteToken', {}).get('symbol', '')
                    
                    if quote_symbol not in ['SOL', 'USDC', 'WSOL']:
                        continue
                    
                    # Exclude only major currencies
                    if base_symbol in ['SOL', 'USDC', 'USDT', 'WSOL']:
                        continue
                    
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0))
                    volume_24h = float(pair.get('volume', {}).get('h24', 0))
                    
                    # Relaxed filters
                    if liquidity > 3000 and volume_24h > 1000:
                        trending.append({
                            'address': pair.get('baseToken', {}).get('address'),
                            'symbol': base_symbol,
                            'name': pair.get('baseToken', {}).get('name'),
                            'price': float(pair.get('priceUsd', 0)),
                            'volume_24h': volume_24h,
                            'volume_6h': float(pair.get('volume', {}).get('h6', 0)),
                            'volume_1h': float(pair.get('volume', {}).get('h1', 0)),
                            'liquidity': liquidity,
                            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
                            'price_change_6h': float(pair.get('priceChange', {}).get('h6', 0)),
                            'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                            'dex_url': pair.get('url')
                        })
                
                logger.info(f"Found {len(trending)} potential coins")
                trending.sort(key=lambda x: x['volume_24h'], reverse=True)
                return trending
                
        except Exception as e:
            logger.error(f"Error fetching coins: {e}")
        
        return []

class OnChainAnalyzer:
    """Analyzes on-chain data using Birdeye API"""
    
    def __init__(self):
        self.base_url = "https://public-api.birdeye.so"
        self.headers = {
            "X-API-KEY": BIRDEYE_API_KEY
        }
    
    def get_token_overview(self, token_address: str) -> Dict:
        """Get comprehensive token data from Birdeye"""
        try:
            url = f"{self.base_url}/defi/token_overview"
            params = {"address": token_address}
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', {})
            else:
                logger.warning(f"Birdeye API returned {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching Birdeye data: {e}")
        
        return {}
    
    def get_holder_info(self, token_address: str) -> Dict:
        """Get holder count and distribution"""
        try:
            url = f"{self.base_url}/defi/token_holder"
            params = {"address": token_address}
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', {})
                
        except Exception as e:
            logger.error(f"Error fetching holder data: {e}")
        
        return {}

class ComprehensiveAnalyzer:
    """Multi-signal analysis combining price action, volume, and on-chain data"""
    
    def __init__(self):
        self.onchain = OnChainAnalyzer()
    
    def analyze(self, coin_data: Dict) -> Dict:
        """
        Comprehensive analysis combining:
        1. Trend direction
        2. Volume confirmation
        3. On-chain holder activity
        4. Volume spike correlation
        """
        
        score = 0
        max_score = 10
        signals = []
        warnings = []
        
        address = coin_data['address']
        
        # ===== 1. TREND DIRECTION (3 points max) =====
        price_6h = coin_data.get('price_change_6h', 0)
        price_24h = coin_data.get('price_change_24h', 0)
        
        # Focus on 4-6h timeframe (sweet spot for meme coins)
        if price_6h > 3:  # Lowered from 5%
            score += 2
            signals.append(f"📈 4-6h uptrend: +{price_6h:.1f}%")
        elif price_6h > 0:
            score += 1
            signals.append(f"📊 Positive 4-6h: +{price_6h:.1f}%")
        
        if price_24h > 0:
            score += 1
            signals.append(f"📈 24h positive: +{price_24h:.1f}%")
        else:
            warnings.append(f"⚠️ 24h negative: {price_24h:.1f}%")
        
        # ===== 2. VOLUME CONFIRMATION (2 points max) =====
        volume_1h = coin_data.get('volume_1h', 0)
        volume_6h = coin_data.get('volume_6h', 0)
        volume_24h = coin_data.get('volume_24h', 0)
        
        # Check if volume is increasing
        avg_hourly = volume_24h / 24 if volume_24h > 0 else 1
        if volume_1h > avg_hourly * 1.5:  # Lowered from 2x
            score += 1
            signals.append(f"🔊 Volume increasing (1h: ${volume_1h:.0f})")
        
        if volume_6h > (volume_24h / 4) * 1.1:  # Lowered from 1.3x
            score += 1
            signals.append("📊 Volume trending up")
        
        # ===== 3. VOLUME SPIKE + PRICE INCREASE (2 points max) =====
        price_1h = coin_data.get('price_change_1h', 0)
        
        # Correlation: both volume AND price increasing
        if price_1h > 0 and volume_1h > avg_hourly * 1.2:  # Lowered from 1.5x
            score += 2
            signals.append(f"⚡ Price+Volume spike: +{price_1h:.1f}% with volume")
        elif price_1h > 3:  # Lowered from 5%
            score += 1
            signals.append(f"🚀 Price spike: +{price_1h:.1f}%")
        
        # Avoid buying tops
        if price_1h > 20:
            score -= 1
            warnings.append(f"⚠️ Possible top - recent pump: +{price_1h:.1f}%")
        
        # ===== 4. ON-CHAIN ANALYSIS (3 points max) =====
        logger.info(f"  Fetching on-chain data for {coin_data['symbol']}...")
        
        try:
            # Get Birdeye data
            token_data = self.onchain.get_token_overview(address)
            
            if token_data:
                # Holder count
                holder_count = token_data.get('holder', 0)
                if holder_count > 1000:
                    score += 1
                    signals.append(f"👥 Strong holder base: {holder_count}")
                elif holder_count > 100:
                    signals.append(f"👥 Growing holders: {holder_count}")
                else:
                    warnings.append(f"⚠️ Low holder count: {holder_count}")
                
                # Unique traders (24h activity)
                unique_traders_24h = token_data.get('uniqueWallet24h', 0)
                if unique_traders_24h > 500:
                    score += 1
                    signals.append(f"🔥 High activity: {unique_traders_24h} traders/24h")
                
                # Top holders concentration (safety check)
                top10_holder_percent = token_data.get('top10HolderPercent', 100)
                if top10_holder_percent < 50:
                    score += 1
                    signals.append(f"✅ Decentralized: Top 10 hold {top10_holder_percent:.1f}%")
                else:
                    warnings.append(f"⚠️ Centralized: Top 10 hold {top10_holder_percent:.1f}%")
                
        except Exception as e:
            logger.warning(f"  Could not fetch on-chain data: {e}")
            warnings.append("⚠️ On-chain data unavailable")
        
        # ===== 5. LIQUIDITY SAFETY (bonus point) =====
        liquidity = coin_data.get('liquidity', 0)
        if liquidity > 50000:
            score += 1
            signals.append(f"💧 Strong liquidity: ${liquidity:.0f}")
        elif liquidity < 5000:
            warnings.append(f"⚠️ Low liquidity: ${liquidity:.0f}")
        
        # Final verdict
        is_bullish = score >= 4  # Lowered from 6 to catch more signals
        
        return {
            'is_bullish': is_bullish,
            'score': score,
            'max_score': max_score,
            'percentage': int((score / max_score) * 100),
            'signals': signals,
            'warnings': warnings,
            'price': coin_data['price'],
            'dex_url': coin_data['dex_url']
        }

def send_telegram(message: str) -> Optional[int]:
    """Send message to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False
        }
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            return response.json().get('result', {}).get('message_id')
        else:
            logger.error(f"Telegram error: {response.text}")
            
    except Exception as e:
        logger.error(f"Error sending Telegram: {e}")
    
    return None

def analyze_and_notify():
    """Main scanning and analysis"""
    global last_notification_time
    
    now = datetime.now()
    if last_notification_time and (now - last_notification_time).seconds < 180:
        logger.info("Waiting for next notification window")
        return
    
    logger.info("\n" + "="*70)
    logger.info("STARTING COMPREHENSIVE SCAN")
    logger.info("="*70)
    
    # Scan for coins
    scanner = SolanaScanner()
    coins = scanner.get_trending_coins()
    
    if not coins:
        logger.info("No coins found")
        return
    
    # Analyze each coin
    analyzer = ComprehensiveAnalyzer()
    candidates = []
    
    for coin in coins[:15]:
        logger.info(f"\n--- {coin['symbol']} ({coin['name']}) ---")
        logger.info(f"    Address: {coin['address']}")
        logger.info(f"    Price: ${coin['price']:.8f}")
        logger.info(f"    Volume 24h: ${coin['volume_24h']:.0f}")
        
        if coin['address'] in recently_notified_coins:
            logger.info("  ⏭ Already notified")
            continue
        
        result = analyzer.analyze(coin)
        
        logger.info(f"\n  📊 ANALYSIS SCORE: {result['score']}/{result['max_score']} ({result['percentage']}%)")
        
        for signal in result['signals']:
            logger.info(f"  {signal}")
        
        for warning in result['warnings']:
            logger.info(f"  {warning}")
        
        if result['is_bullish']:
            logger.info(f"  ✅ BULLISH SIGNAL")
            candidates.append({'coin': coin, 'analysis': result})
        else:
            logger.info(f"  ❌ Not bullish (score too low)")
    
    if not candidates:
        logger.info("\n❌ No bullish coins found this cycle")
        return
    
    # Pick best candidate
    best = max(candidates, key=lambda x: x['analysis']['score'])
    coin = best['coin']
    analysis = best['analysis']
    
    logger.info(f"\n🎯 BEST OPPORTUNITY: {coin['symbol']}")
    logger.info(f"   Score: {analysis['score']}/{analysis['max_score']} ({analysis['percentage']}%)")
    
    # Send notification
    message = f"""
🚀 <b>BUY SIGNAL - {coin['symbol']}</b>

<b>Token:</b> {coin['name']}
<b>Address:</b> <code>{coin['address']}</code>
<b>Price:</b> ${analysis['price']:.8f}

<b>📊 ANALYSIS SCORE: {analysis['score']}/{analysis['max_score']} ({analysis['percentage']}%)</b>

<b>✅ BULLISH SIGNALS:</b>
{chr(10).join('• ' + s for s in analysis['signals'])}

{f"<b>⚠️ WARNINGS:</b>{chr(10)}{chr(10).join('• ' + w for w in analysis['warnings'])}{chr(10)}" if analysis['warnings'] else ""}
<b>💰 Trade Setup:</b>
• Amount: {SOL_PER_TRADE} SOL
• Target: +5% (${analysis['price'] * 1.05:.8f})
• Hold: 48h if target not hit

<b>📈 Chart:</b> {analysis['dex_url']}

<b>Reply YES to execute or NO to skip</b>
"""
    
    msg_id = send_telegram(message.strip())
    
    if msg_id:
        last_notification_time = now
        pending_approvals[msg_id] = best
        recently_notified_coins.append(coin['address'])
        
        if len(recently_notified_coins) > 20:
            recently_notified_coins.pop(0)
        
        logger.info("✅ Notification sent!")

def check_telegram_responses():
    """Check for user responses"""
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
                    logger.info("✅ User approved trade!")
                    # TODO: Execute buy in Phase 2
                    
    except Exception as e:
        logger.error(f"Error checking responses: {e}")

def monitor_positions():
    """Monitor active positions"""
    # TODO: Phase 2
    pass

def main():
    """Main bot loop"""
    logger.info("="*70)
    logger.info("SOLANA MEME COIN TRADING AGENT V2")
    logger.info("Multi-Signal Analysis: Trend + Volume + On-Chain + Holders")
    logger.info(f"Wallet: {WALLET_ADDRESS}")
    logger.info("="*70)
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✓ Flask server started")
    
    time.sleep(2)
    
    # Startup message
    send_telegram("🤖 Solana Agent V2 Active!\n\n📊 Multi-signal analysis enabled:\n• Trend direction\n• Volume confirmation\n• On-chain holder data\n• Volume spike correlation\n\n⏱ Scanning every 15 min")
    
    # First scan
    analyze_and_notify()
    
    # Schedule
    schedule.every(SCAN_INTERVAL_MINUTES).minutes.do(analyze_and_notify)
    schedule.every(1).minutes.do(check_telegram_responses)
    schedule.every(5).minutes.do(monitor_positions)
    
    logger.info("\n✓ Agent running...\n")
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
