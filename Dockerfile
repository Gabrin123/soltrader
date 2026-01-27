FROM python:3.11-slim

WORKDIR /app

COPY requirements_trading.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY solana_trading_agent.py .

CMD ["python", "solana_trading_agent.py"]
