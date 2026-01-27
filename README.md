# Solana Meme Coin Trading Agent
**Strategy: Ivan on Tech's Money Line + Social Sentiment Analysis**

## 🎯 What This Bot Does

### Phase 1 (Current - Monitoring & Alerts):
1. **Scans** for new/trending Solana meme coins every 15 minutes
2. **Analyzes** using Money Line strategy:
   - Positive 1h momentum
   - Strong volume
   - Not buying tops
   - Good liquidity
3. **Checks** social sentiment on X (Twitter) and TikTok
4. **Sends** ONE buy signal per hour (best opportunity only)
5. **Waits** for your YES/NO approval before executing

### Phase 2 (After Testing - Trade Execution):
- Executes approved trades automatically
- Monitors positions for 5% profit target
- Sends notification to sell or hold for another 5%
- After 48h, asks if you want to sell or continue holding

## 📋 Setup Instructions

### 1. Deploy on Render.com

**Create New Web Service:**
1. Go to render.com
2. Create new Web Service from GitHub
3. Settings:
   - **Environment**: Docker
   - **Instance Type**: Free

**Environment Variables:**
```
BOT_TOKEN=8457965430:AAHERt3c9hX118RcVGLoxu1OZFyePK1c7dI
CHAT_ID=-5232036612
WALLET_ADDRESS=8hZfubBEVqJGF73a4x9f8XFKgNRmHxdz9p81pScRzGmo
SOL_PER_TRADE=0.1
SOLANA_PRIVATE_KEY=(leave empty for Phase 1)
```

### 2. Keep Bot Awake (UptimeRobot)

Since this bot needs 24/7 monitoring:
1. Go to uptimerobot.com
2. Add monitor with your Render URL
3. Set interval to 5 minutes

### 3. Testing Phase

**What to expect:**
- Bot sends startup message
- Scans every 15 minutes
- Sends MAX 1 buy signal per hour
- Each signal includes:
  - Coin details
  - Money Line score & reasons
  - Social sentiment summary
  - Chart link
  - Price and trade setup

**How to respond:**
- Reply "YES" to approve (currently logs only, no execution)
- Reply "NO" to skip
- No response = skip after 5 minutes

## 🔧 Strategy Details

### Money Line Scoring (0-6 points):
- +2: Positive 1h price momentum
- +2: Volume above average
- +1: Not at immediate top (< 10% pump in 5min)
- +1: Liquidity > $10k
- **Bullish threshold: 4+ points**

### Social Signals (Need minimum 1):
- **X (Twitter)**: Recent mentions with bullish sentiment
- **TikTok**: Videos about the coin in last 24h

### Filters:
- Liquidity: $1k - $500k (targets newer coins)
- Volume: > $5k in 24h
- Not buying 5min pumps (avoids tops)

## 📊 Trade Management (Phase 2)

**Entry:**
- Amount: Configurable (default 0.1 SOL)
- No stop loss (hold for 48h minimum)

**Exit Strategy:**
- Target 1: +5% → Ask to sell or hold for another +5%
- Target 2: +10% → Ask to sell or continue
- After 48h: Ask regardless of profit

## 🔐 Security Notes

**Phase 1 (Current):**
- No private key needed
- No trades executed
- Safe testing mode

**Phase 2 (Trading):**
- Private key stored as environment variable in Render (encrypted)
- Only executes after your YES approval
- You maintain full control

## 📱 Telegram Commands

Currently responds to:
- "YES" / "BUY" → Approves trade (Phase 2)
- "NO" / "SKIP" → Rejects signal

## ⚙️ Configuration

Edit environment variables in Render:
- `SOL_PER_TRADE`: Amount per trade (default: 0.1)
- `SCAN_INTERVAL_MINUTES`: Currently 15 (in code)
- `PROFIT_TARGET`: Currently 5% (in code)
- `HOLD_PERIOD_HOURS`: Currently 48h (in code)

## 📈 Performance Tracking

The bot logs:
- How many coins scanned
- How many passed Money Line filter
- How many had social signals
- Best opportunity and why
- All scores and reasoning

Check Render logs to see decision-making process.

## ⚠️ Risk Warnings

- Meme coins are extremely volatile
- Most lose 90%+ of value quickly
- Social signals can be manipulated
- Always start with small amounts
- This is experimental - no guarantees

## 🚀 Next Steps

1. **Deploy and test Phase 1** (monitoring only)
2. **Observe signals for 1-2 weeks**
3. **Verify strategy quality**
4. **Add private key for Phase 2** (real trading)

## 🛠️ Files

- `solana_trading_agent.py` - Main bot
- `requirements_trading.txt` - Dependencies  
- `Dockerfile_trading` - Docker config (rename to Dockerfile)
- This README

## 📞 Support

Monitor Render logs for detailed information about:
- What coins are being analyzed
- Why they pass/fail filters
- Score breakdowns
- Any errors

---

**Remember**: Start small, test thoroughly, and never risk more than you can afford to lose!
