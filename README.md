# Axiom Alerts desktop app

This Windows desktop app watches Axiom's `new_pairs` WebSocket feed and sends one Discord alert per coin when its USD market cap is first observed between $5,000 and $20,000. When Axiom reports market cap in SOL, the bot uses CoinGecko's current SOL/USD price for conversion.

The monitor only runs while the app is open and started. Press **Stop monitor** or close the window to end it.

## Setup

1. Rotate the Discord webhook that was shared in chat. Copy `.env.example` to `.env` and put the new webhook URL in it.
2. While signed in to Axiom, open your browser's developer tools, go to **Application**, then **Cookies**, then `https://axiom.trade`. Copy the values of `auth-access-token` and `auth-refresh-token` into `.env`.
3. Install the Python and desktop dependencies:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
```

4. Run the desktop app:

```powershell
npm start
```

Use **Start monitor** and **Stop monitor** inside the app. Closing the app also stops the Python monitor process.

## Build the Windows application

```powershell
npm run build
```

The portable executable is created in `dist`. Keep `.env` beside the portable executable so the app can load your credentials.

The Axiom Python client used here is community-maintained because Axiom does not currently publish a supported public market-data API. Axiom can change its private WebSocket format without notice.
