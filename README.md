# Axiom Discord alerts

This bot watches Axiom's `new_pairs` WebSocket feed and sends one Discord alert per coin when its USD market cap is first observed between $5,000 and $20,000. When Axiom reports market cap in SOL, the bot uses CoinGecko's current SOL/USD price for conversion. Alerted token addresses are saved in `alerted_coins.json`, so restarting the bot does not send duplicates.

## Setup

1. Rotate the Discord webhook that was shared in chat. Copy `.env.example` to `.env` and put the new webhook URL in it.
2. While signed in to Axiom, open your browser's developer tools, go to **Application**, then **Cookies**, then `https://axiom.trade`. Copy the values of `auth-access-token` and `auth-refresh-token` into `.env`.
3. Install and run the bot from PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bot.py
```

Keep the terminal running. Stop the bot with Ctrl+C.

The Axiom Python client used here is community-maintained because Axiom does not currently publish a supported public market-data API. Axiom can change its private WebSocket format without notice.
