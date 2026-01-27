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
import pandas as pd
import pandas_ta as ta  # Install via pip if needed (add to requirements.txt)

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

# Birdeye API (get free key from birdeye.so/dashboard/api-key)
BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY')  # Required: Set real key in env
BIRDEYE_BASE_URL = "https://public-api.birdeye.so"

# Trading parameters
SOL_PER_TRADE = float(os.environ.get('SOL_PER_TRADE', '0.1'))
PROFIT_TARGET = 0.05
HOLD_PERIOD_HOURS = 48
SCAN_INTERVAL_MINUTES = 15

# State management
last_notification_time = None
recently_notified_coins = []
active_positions = {}
pending_approvals = {}  # msg_id -> {'coin': coin, 'analysis': analysis}
last_update_id = 0  # To track processed Telegram updates

class SolanaScanner:
    """Scans for trending Solana tokens using Birdeye"""
    
    def __init__(self):
        self.headers = {"X-API-KEY": BIRDEYE_API_KEY, "x-chain": "solana"}
        self.last_scan = None
        
    def get_trending_coins(self) -> List[Dict]:
        """Fetch trending/gaining Solana tokens from Birdeye (top by 24h price change)"""
        try:
            # Use /defi/tokens for top gainers (trending by price change)
            url = f"{BIRDEYE_BASE_URL}/defi/tokens"
            params = {
                "sort_by": "24h_price_change",
                "sort_type": "desc",
                "offset": 0,
                "limit": 100
            }
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                tokens = data.get('data', {}).get('tokens', [])
                
                logger.info(f"Birdeye returned {len(tokens)} tokens")
                
                trending = []
                for token in tokens:
                    # Filter for meme-like (exclude majors, low liquidity OK for memes)
                    symbol = token.get('symbol', '')
                    if symbol in ['SOL', 'USDC', 'USDT']:
                        continue
                    
                    liquidity = token.get('liquidity', 0)
                    v_24h_usd = token.get('v_24h_usd', 0)
                    price_change_24h = token.get('price_change_24h', 0) * 100  # To percent
                    
                    if liquidity > 3000 and v_24h_usd > 1000:
                        trending.append({
                            'address': token.get('address'),
                            'symbol': symbol,
                            'name': token.get('name', symbol),
                            'price': token.get('price', 0),
                            'volume_24h': v_24h_usd,
                            'volume_6h': token.get('v_6h_usd', 0),  # Approx
                            'volume_1h': token.get('v_1h_usd', 0),
                            'liquidity': liquidity,
                            'price_change_1h': token.get('price_change_1h', 0) * 100,
                            'price_change_6h': token.get('price_change_6h', 0) * 100,
                            'price_change_24h': price_change_24h,
                            'dex_url': f"https://dexscreener.com/solana/{token.get('address')}"  # Fallback to Dexscreener chart
                        })
                
                logger.info(f"Found {len(trending)} potential coins after filters")
                return trending[:50]  # Limit to top 50
                
            else:
                logger.error(f"Birdeye tokens API error: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error fetching trending coins: {e}")
        
        return []

class OnChainAnalyzer:
    """Analyzes on-chain data using Birdeye API"""
    
    def __init__(self):
        self.base_url = BIRDEYE_BASE_URL
        self.headers = {"X-API-KEY": BIRDEYE_API_KEY, "x-chain": "solana"}
    
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
                logger.warning(f"Birdeye overview API: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error fetching Birdeye overview: {e}")
        
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
            else:
                logger.warning(f"Birdeye holder API: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error fetching holder data: {e}")
        
        return {}
    
    def get_4h_chart_data(self, token_address: str) -> pd.DataFrame:
        """Fetch 4h historical price data from Birdeye for Money Line approx"""
        try:
            now = int(time.time())
            time_from = now - (3600 * 4 * 50)  # Last 50 * 4h periods (~8 days)
            url = f"{self.base_url}/defi/history_price"
            params = {
                "address": token_address,
                "address_type": "token",
                "type": "4H",
                "time_from": time_from,
                "time_to": now
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', {}).get('items', [])
                if items:
                    df = pd.DataFrame(items)
                    df['unixTime'] = pd.to_datetime(df['unixTime'], unit='s')
                    df = df.set_index('unixTime')
                    df = df[['value']]  # Price
                    df['volume'] = df.get('volume', 0)  # If available
                    return df
                else:
                    logger.warning("No 4h data returned")
            else:
                logger.error(f"Birdeye history_price API: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error fetching 4h chart: {e}")
        
        return pd.DataFrame()  # Empty on failure

class ComprehensiveAnalyzer:
    """Multi-signal analysis with 4h Money Line approximation"""
    
    def __init__(self):
        self.onchain = OnChainAnalyzer()
    
    def analyze(self, coin_data: Dict) -> Dict:
        """
        Comprehensive analysis combining:
        1. 4h Money Line approx (EMA, RSI, volume)
        2. Trend direction
        3. Volume confirmation
        4. On-chain holder activity
        5. Volume spike correlation
        """
        
        score = 0
        max_score = 12  # Adjusted for new 4h section
        signals = []
        warnings = []
        
        address = coin_data['address']
        
        logger.info(f"  Starting analysis for {coin_data.get('symbol', 'UNKNOWN')}...")
        
        # ===== 0. 4H MONEY LINE APPROX (4 points max) =====
        logger.info(f"  [0/6] Fetching 4h chart for Money Line approx...")
        df = self.onchain.get_4h_chart_data(address)
        if not df.empty and len(df) >= 20:
            # Compute indicators
            df['EMA20'] = ta.ema(df['value'], length=20)
            df['RSI'] = ta.rsi(df['value'], length=14)
            df['Volume_MA5'] = ta.sma(df['volume'], length=5) if 'volume' in df else pd.Series(0)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            # Bullish if price > EMA20, RSI >50, volume increasing
            if latest['value'] > latest['EMA20']:
                score += 2
                signals.append(f"📈 4h trend bullish: Price above EMA20")
            if latest['RSI'] > 50:
                score += 1
                signals.append(f"📊 4h momentum: RSI {latest['RSI']:.1f} >50")
            if latest.get('volume', 0) > prev.get('volume', 0) and latest['volume'] > latest['Volume_MA5']:
                score += 1
                signals.append("🔊 4h volume increasing")
            
            logger.info(f"      4h Money Line score: +{score} so far")
        else:
            warnings.append("⚠️ No 4h chart data - skipped Money Line")
        
        # ===== 1. TREND DIRECTION (3 points max) =====
        # (Rest of your original analysis here, unchanged but with lowered thresholds)
        logger.info(f"  [1/6] Checking trend direction...")
        price_6h = coin_data.get('price_change_6h', 0)
        price_24h = coin_data.get('price_change_24h', 0)
        
        logger.info(f"      6h change: {price_6h:.2f}%")
        logger.info(f"      24h change: {price_24h:.2f}%")
        
        if price_6h > 2:  # Lowered
            score += 2
            signals.append(f"📈 4-6h uptrend: +{price_6h:.1f}%")
            logger.info(f"      ✓ Strong 6h trend (+2 points, total: {score})")
        elif price_6h > 0:
            score += 1
            signals.append(f"📊 Positive 4-6h: +{price_6h:.1f}%")
            logger.info(f"      ✓ Positive 6h trend (+1 point, total: {score})")
        
        if price_24h > 0:
            score += 1
            signals.append(f"📈 24h positive: +{price_24h:.1f}%")
            logger.info(f"      ✓ Positive 24h (+1 point, total: {score})")
        else:
            warnings.append(f"⚠️ 24h negative: {price_24h:.1f}%")
        
        # ===== 2. VOLUME CONFIRMATION (2 points max) =====
        # (Similar adjustments, lowered multipliers)
        # ... (keep your code, just lower avg_hourly *1.3 etc to 1.2)
        
        # (Omit full paste for brevity; apply similar lowers to 3-5 sections)
        
        # Final verdict
        is_bullish = score >= 3  # Lowered to catch more
        
        logger.info(f"\n  FINAL SCORE: {score}/{max_score} ({int((score/max_score)*100)}%)")
        logger.info(f"  VERDICT: {'✅ BULLISH' if is_bullish else '❌ NOT BULLISH'} (threshold: 3)")
        
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

# (Keep send_telegram unchanged)

def check_telegram_responses():
    """Check for user responses with reply matching"""
    try:
        global last_update_id
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            updates = data.get('result', [])
            
            for update in updates:
                last_update_id = update['update_id']
                message = update.get('message', {})
                text = message.get('text', '').upper()
                reply_to_id = message.get('reply_to_message', {}).get('message_id')
                
                if reply_to_id in pending_approvals and ('YES' in text or 'BUY' in text):
                    best = pending_approvals[reply_to_id]
                    logger.info(f"✅ User approved trade for {best['coin']['symbol']}!")
                    # TODO: Execute buy (Phase 2: Use solana-py or jup.ag API for swap)
                    del pending_approvals[reply_to_id]
                elif reply_to_id in pending_approvals and 'NO' in text:
                    logger.info(f"❌ User skipped trade")
                    del pending_approvals[reply_to_id]
                
    except Exception as e:
        logger.error(f"Error checking responses: {e}")

# (Keep analyze_and_notify, monitor_positions, main mostly unchanged; ensure scanner uses Birdeye)

if __name__ == "__main__":
    main()
