# Axiom Alerts desktop app

This Windows desktop app watches Axiom's live new-pair and price feeds. It starts a timer when a coin reaches the starting market cap, then sends one Discord alert if that coin reaches the target market cap before the movement window expires. The defaults are $5,000 to $20,000 within 40 seconds.

The monitor only runs while the app is open and started. Press **Stop monitor** or close the window to end it.

On Windows PCs that block unsigned desktop applications, double-click `Start Axiom Alerts.cmd`. It opens the same interface as a local browser app at `http://127.0.0.1:8765` without exposing it to the network. Use the red close button to stop the monitor and local server.

Use **Settings** inside the app to edit the starting cap, target cap, movement window, Discord webhook, Axiom tokens, and optional Cloudflare clearance value. The settings are stored only in the local `.env` file.

## Setup

1. Copy `.env.example` to `.env`, or open **Settings** in the desktop app and enter the values there.
2. While signed in to Axiom, open your browser's developer tools, go to **Application**, then **Cookies**, then `https://axiom.trade`. Copy the values of `auth-access-token` and `auth-refresh-token` into the matching settings fields.
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

Use **Start monitor** and **Stop monitor** inside the app. Closing the app also stops the Python monitor process. Stop the monitor before saving configuration changes.

When an alert fires, click the coin in Recent Activity or use **Open in Axiom** to open its trading page. Use **Copy address** to put the coin address on your clipboard. Discord alerts also link their title and **View coin** action to the same Axiom page.

Discord alerts include an automated rug-risk rating out of 10 with evidence for deployer history, mint and freeze authority, metadata control, liquidity locking, holder and developer concentration, insider wallets, and Axiom bundle percentage. The deployer check links the creator wallet, counts its prior launches, and flags RugCheck's rugged-token history finding. The rating uses RugCheck and Axiom data as a screening signal, not a guarantee that a token is safe or fraudulent.

## Build the Windows application

Copy `.env.signing.example` to `.env.signing`, then set `WIN_CSC_LINK` to your trusted `.pfx` certificate and `WIN_CSC_KEY_PASSWORD` to its password. The signing file is ignored by Git and must stay private.

```powershell
Copy-Item .env.signing.example .env.signing
npm run build
```

The build fails instead of producing an unsigned release when the certificate is missing or invalid. The signed portable executable is created in `dist`. Keep `.env` beside the portable executable so the app can load your credentials.

The Axiom Python client used here is community-maintained because Axiom does not currently publish a supported public market-data API. The monitor subscribes to Axiom's current `new_pairs` stream and each pair's live `b-<pair address>` price room. Axiom can change this private WebSocket format without notice.
