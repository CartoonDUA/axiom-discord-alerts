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

Click **Settings** in Axiom Alerts. Follow the complete setup guide below, click **Save settings**, then click **Start monitor**.

## Complete settings guide

### Connect your Axiom account

1. Sign in at [Axiom](https://axiom.trade/) in Chrome, Edge, or another Chromium browser.
2. Press `F12` or `Ctrl+Shift+I` to open Developer Tools.
3. Open **Application**. If it is hidden, click the `>>` menu first.
4. In the left sidebar, open **Cookies** and select `https://axiom.trade`.
5. Find `auth-access-token`, double-click its **Value**, and copy the complete value into **Axiom account → Access token** in the app.
6. Copy the value of `auth-refresh-token` into **Refresh token**.
7. Leave **Cloudflare clearance** empty unless Axiom Alerts reports a Cloudflare connection problem. If it is needed, copy the `cf_clearance` cookie value into that field.

These values give access to your Axiom session. Never post them in Discord, commit them to GitHub, or send them to another person. Axiom Alerts stores them only in the local `.env` file, which is ignored by Git. If Axiom logs you out or the monitor reports an authentication error, sign in again and copy the new token values.

### Create a Discord webhook

You need at least one webhook for completed alerts. A webhook posts to the specific Discord channel selected when it is created; it does not require the `/check` bot.

1. In Discord, open your server and go to **Server Settings → Integrations → Webhooks**.
2. Click **New Webhook** or **Create Webhook**.
3. Give it a name, choose the channel that should receive alerts, and click **Copy Webhook URL**.
4. In Axiom Alerts, paste the URL into **Alert routing → All alerts → Webhook URL**.

Discord's official [Intro to Webhooks](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) has screenshots of this process. Treat each webhook URL like a password: anyone who has it can post in that channel. Delete and recreate the webhook in Discord if its URL is ever exposed.

For the simplest setup, create one webhook and put it in **All alerts**. To receive the early Premium Momentum and Green Candle messages too, paste that URL into **Green Candle**, or create a second webhook connected to a separate momentum channel.

### Choose where each alert goes

| App field | What it sends |
| --- | --- |
| **All alerts** | Every coin that completes the configured market-cap move. This is the recommended main webhook. |
| **Green Candle** | Early Premium Momentum calls and the later Green Candle follow-up when the configured gain is reached. |
| **Higher risk** | Completed alerts whose rug-risk rating is at or above its threshold. |
| **Lower risk** | Completed alerts at or above its threshold that did not match the higher-risk threshold. |

The rug-risk number measures danger, not quality: `8/10` is riskier than `2/10`. For example, with **Higher risk** set to `4` and **Lower risk** set to `2`, a `6/10` coin goes to the higher-risk webhook, a `3/10` coin goes to the lower-risk webhook, and a `1/10` coin goes to neither risk webhook. **All alerts** still receives every completed alert. Leave either optional risk webhook empty to disable that route.

The Green Candle controls work like this:

- **Gain from tracked market cap** sends the Green Candle follow-up after that percentage gain.
- **Early momentum gain** is the smaller rise needed for an early Premium Momentum call.
- **Momentum window** is how quickly the early rise must happen.
- **Hold gain before calling** requires the rise to stay above the threshold for that many seconds before the call is sent.

### Enable `/check` and the status channel

This part is optional. It lets you type `/check` with a Solana coin address in Discord and lets Axiom Alerts show its online or offline status in a channel.

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Open the application's **Bot** page. Create the bot if Discord asks, then click **Reset Token** and copy the token into **Discord /check command → Bot token** in Axiom Alerts.
3. Open the application's **Installation** page. For a server installation, add the `applications.commands` and `bot` scopes. Give the bot **View Channels**, **Send Messages**, **Embed Links**, and **Use Application Commands** permissions.
4. Copy the installation link, open it, choose your Discord server, and authorize the bot.
5. In Discord, open **User Settings → Advanced** and enable **Developer Mode**.
6. Right-click your server icon, choose **Copy Server ID**, and paste it into **Server ID**. Using a server ID makes `/check` appear in that server immediately after the bot starts.
7. Right-click the channel that should display the bot status, choose **Copy Channel ID**, and paste it into **Status channel ID**. Make sure the bot can view and send messages in that channel.

Discord's official guides explain [creating a bot and installing it](https://docs.discord.com/developers/quick-start/getting-started) and [copying server and channel IDs](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID). The bot token is a secret. Never use the public application ID, public key, or client secret in the **Bot token** field.

After starting the monitor, type `/check`, select the command, paste a Solana coin address into `ca`, and send it. The bot replies with the current automated rug-risk report. The status channel displays the app's running state when a bot token and status channel ID are configured.

### Configure coin movement and audit filters

- **From** is the market cap where the timer begins.
- **Maximum tracking entry** allows a newly discovered coin to enter slightly above **From** without accepting coins that are already too far into the move.
- **To** is the market cap required to complete the alert.
- **Within** is the number of seconds allowed between the starting and target caps.
- **Audit filters** decide which new coins are eligible before tracking begins. The coin must pass every enabled filter.
- Set **Maximum top 10 holders**, **Maximum developer holding**, or **Maximum snipers** to `0` to disable that individual concentration filter.
- **Require Twitter** rejects coins without a Twitter/X link. **Require revoked authorities** rejects coins with active mint or freeze control.

The default movement is `$5,000` to `$20,000` within `40` seconds, with a maximum tracking entry of `$7,500`. Lowering minimum filters or widening the entry cap increases traffic, but it can also admit weaker coins.

### Save and test the setup

1. If the monitor is running, click **Stop monitor**.
2. Open **Settings**, enter the values, and click **Save settings**.
3. Click **Start monitor** and wait for the status at the top of the app to show **Connected**.
4. If `/check` is enabled, run a test check in Discord.
5. Keep the Axiom Alerts window open while monitoring. Click **Stop monitor** or close the app to stop it.

Do not edit or upload `.env` manually unless you know what you are doing. Settings saved through the app update that file automatically, and Git is configured to exclude it.

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
