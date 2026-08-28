# Axiom Alerts desktop app

This Windows desktop app watches Axiom's live new-pair and price feeds. It starts a timer when a coin reaches the starting market cap, then sends one Discord alert if that coin reaches the target market cap before the movement window expires. The defaults are $5,000 to $20,000 within 40 seconds.

The monitor only runs while the app is open and started. Press **Stop monitor** or close the window to end it.

On Windows PCs that block unsigned desktop applications, double-click `Start Axiom Alerts.cmd`. It opens the same interface as a local browser app at `http://127.0.0.1:8765` without exposing it to the network. Use the red close button to stop the monitor and local server.

Use **Settings** inside the app to edit the starting cap, target cap, movement window, Discord webhook, Axiom tokens, and optional Cloudflare clearance value. The settings are stored only in the local `.env` file.

## Easy installation on Windows

### 1. Download the project

Click **Code**, then **Download ZIP** on GitHub. Extract the ZIP somewhere easy to find, such as your Desktop.

### 2. Install the required programs

Install [Python](https://www.python.org/downloads/) and [Node.js](https://nodejs.org/). Keep the default installation options enabled.

### 3. Install the project

Open the extracted `axiom-discord-alerts` folder. Right-click an empty area inside the folder and select **Open in Terminal**, then run:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
```

You only need to run these installation commands once.

### 4. Open Axiom Alerts

Double-click `Start Axiom Alerts.cmd`. The app opens at `http://127.0.0.1:8765` and stops when you close its command window.

### 5. Add your settings

Click **Settings** and add:

- Your Discord webhook URL.
- Your Axiom access token.
- Your Axiom refresh token.
- Your Discord bot token and server ID if you want the `/check` command.

To find the Axiom tokens, sign in to Axiom and open your browser's developer tools. Go to **Application** → **Cookies** → `https://axiom.trade`, then copy `auth-access-token` and `auth-refresh-token` into the matching fields.

Click **Save settings**, then **Start monitor**. Your private settings are saved only in the local `.env` file, which Git ignores.

## Alternative Electron window

After completing the installation above, you can open the Electron version with:

```powershell
npm start
```

Use **Start monitor** and **Stop monitor** inside the app. Closing the app also stops the Python monitor process. Stop the monitor before saving configuration changes.

When an alert fires, click the coin in Recent Activity or use **Open in Axiom** to open its trading page. Use **Copy address** to put the coin address on your clipboard. Discord alerts also link their title and **View coin** action to the same Axiom page.

Discord alerts include an automated rug-risk rating out of 10 with evidence for deployer history, mint and freeze authority, metadata control, liquidity locking, holder and developer concentration, insider wallets, connected-wallet bubble clusters, and Axiom bundle percentage. Bubble analysis reports how many linked clusters were found, the wallets in the largest cluster, and the percentage of supply it controls. The deployer check links the creator wallet, counts its prior launches, and flags RugCheck's rugged-token history finding. The rating uses RugCheck and Axiom data as a screening signal, not a guarantee that a token is safe or fraudulent.

## Read-only GitHub Pages dashboard

The `docs` folder contains a public dashboard for GitHub Pages. It displays only the Coin Movement settings, Audit Filters, active tracked coins, and safe monitor events. Webhooks, Discord credentials, Axiom tokens, and every other `.env` value are excluded from the public API.

Open the dashboard on the same PC as Axiom Alerts and allow the browser's local-network permission when prompted. The page reads the backend at `http://127.0.0.1:8765`, so the desktop app must remain open. Changes made in the desktop app appear on the dashboard automatically.

## Build the Windows application

Copy `.env.signing.example` to `.env.signing`, then set `WIN_CSC_LINK` to your trusted `.pfx` certificate and `WIN_CSC_KEY_PASSWORD` to its password. The signing file is ignored by Git and must stay private.

```powershell
Copy-Item .env.signing.example .env.signing
npm run build
```

The build fails instead of producing an unsigned release when the certificate is missing or invalid. The signed portable executable is created in `dist`. Keep `.env` beside the portable executable so the app can load your credentials.

The Axiom Python client used here is community-maintained because Axiom does not currently publish a supported public market-data API. The monitor subscribes to Axiom's current `new_pairs` stream and each pair's live `b-<pair address>` price room. Axiom can change this private WebSocket format without notice.
