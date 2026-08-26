import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import requests
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser


APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env"
STATUS_FILE = APP_DIR / "discord_status.json"
RENDERER_DIR = APP_DIR / "renderer"
FONTAWESOME_DIR = APP_DIR / "node_modules" / "@fortawesome" / "fontawesome-free"
HOST = "127.0.0.1"
PORT = 8765
PUBLIC_ORIGINS = {"https://cartoondua.github.io", "http://127.0.0.1:8766"}

SETTING_DEFAULTS = {
    "DISCORD_WEBHOOK_URL": "",
    "DISCORD_ALL_WEBHOOK_URL": "",
    "DISCORD_GREEN_CANDLE_WEBHOOK_URL": "",
    "GREEN_CANDLE_PERCENT": "100",
    "EARLY_MOMENTUM_PERCENT": "10",
    "EARLY_MOMENTUM_WINDOW_SECONDS": "15",
    "EARLY_MOMENTUM_HOLD_SECONDS": "2",
    "DISCORD_WEBHOOK_MIN_RATING": "4",
    "DISCORD_SECONDARY_WEBHOOK_URL": "",
    "DISCORD_SECONDARY_MIN_RATING": "2",
    "DISCORD_BOT_TOKEN": "",
    "DISCORD_GUILD_ID": "",
    "DISCORD_STATUS_CHANNEL_ID": "",
    "AXIOM_ACCESS_TOKEN": "",
    "AXIOM_REFRESH_TOKEN": "",
    "CF_CLEARANCE": "",
    "START_MARKET_CAP": "5000",
    "TARGET_MARKET_CAP": "20000",
    "MAX_TRACKING_ENTRY_CAP": "7500",
    "MOVE_WINDOW_SECONDS": "40",
    "AUDIT_MAX_AGE_MINUTES": "15",
    "AUDIT_MIN_PRO_TRADERS": "0",
    "AUDIT_MIN_MARKET_CAP": "5000",
    "AUDIT_MIN_GLOBAL_FEES_SOL": "0",
    "AUDIT_REQUIRE_TWITTER": "true",
    "AUDIT_MAX_TOP_10_PERCENT": "20",
    "AUDIT_MAX_DEV_HOLDING_PERCENT": "10",
    "AUDIT_MAX_SNIPER_PERCENT": "10",
    "AUDIT_REQUIRE_REVOKED_AUTHORITIES": "true",
}

bot_process = None
stopping = False
events = []
event_number = 0
tracked_coins = {}
monitor_status = {"state": "stopped", "label": "Stopped"}
server = None
lock = threading.Lock()


def read_settings():
    settings = SETTING_DEFAULTS.copy()
    if not ENV_FILE.exists():
        return settings

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match or match.group(1) not in settings:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        settings[match.group(1)] = value
    return settings


def credentials_ready():
    settings = read_settings()
    has_webhook = settings["DISCORD_ALL_WEBHOOK_URL"] or settings["DISCORD_WEBHOOK_URL"]
    return bool(has_webhook and settings["AXIOM_ACCESS_TOKEN"] and settings["AXIOM_REFRESH_TOKEN"])


def save_settings(values):
    if bot_process:
        return {"ok": False, "error": "Stop the monitor before changing settings."}

    settings = {}
    for name, fallback in SETTING_DEFAULTS.items():
        value = values.get(name, fallback)
        settings[name] = str(value).strip().replace("\r", "").replace("\n", "")

    start = float(settings["START_MARKET_CAP"])
    target = float(settings["TARGET_MARKET_CAP"])
    max_entry = float(settings["MAX_TRACKING_ENTRY_CAP"])
    seconds = float(settings["MOVE_WINDOW_SECONDS"])
    primary_rating = float(settings["DISCORD_WEBHOOK_MIN_RATING"])
    secondary_rating = float(settings["DISCORD_SECONDARY_MIN_RATING"])
    audit_age = float(settings["AUDIT_MAX_AGE_MINUTES"])
    audit_pro_traders = float(settings["AUDIT_MIN_PRO_TRADERS"])
    audit_market_cap = float(settings["AUDIT_MIN_MARKET_CAP"])
    audit_fees = float(settings["AUDIT_MIN_GLOBAL_FEES_SOL"])
    audit_top_ten = float(settings["AUDIT_MAX_TOP_10_PERCENT"])
    audit_developer = float(settings["AUDIT_MAX_DEV_HOLDING_PERCENT"])
    audit_snipers = float(settings["AUDIT_MAX_SNIPER_PERCENT"])
    green_candle_percent = float(settings["GREEN_CANDLE_PERCENT"])
    early_momentum_percent = float(settings["EARLY_MOMENTUM_PERCENT"])
    early_momentum_window = float(settings["EARLY_MOMENTUM_WINDOW_SECONDS"])
    early_momentum_hold = float(settings["EARLY_MOMENTUM_HOLD_SECONDS"])
    if start <= 0:
        return {"ok": False, "error": "Starting market cap must be above zero."}
    if target <= start:
        return {"ok": False, "error": "Target market cap must be above the starting cap."}
    if not start <= max_entry < target:
        return {"ok": False, "error": "Maximum tracking entry must be between the starting and target caps."}
    if seconds <= 0:
        return {"ok": False, "error": "Movement window must be above zero seconds."}
    if not 0 <= primary_rating <= 10 or not 0 <= secondary_rating <= 10:
        return {"ok": False, "error": "Webhook rug ratings must be between 0 and 10."}
    if min(audit_age, audit_pro_traders, audit_market_cap, audit_fees, audit_top_ten, audit_developer, audit_snipers) < 0:
        return {"ok": False, "error": "Audit filter values cannot be negative."}
    if max(audit_top_ten, audit_developer, audit_snipers) > 100:
        return {"ok": False, "error": "Holding percentages cannot be above 100%."}
    if green_candle_percent <= 0:
        return {"ok": False, "error": "Green Candle percentage must be above zero."}
    if early_momentum_percent <= 0 or early_momentum_window <= 0 or early_momentum_hold < 0:
        return {"ok": False, "error": "Momentum gain and window must be positive; hold time cannot be negative."}

    settings["START_MARKET_CAP"] = str(int(start) if start.is_integer() else start)
    settings["TARGET_MARKET_CAP"] = str(int(target) if target.is_integer() else target)
    settings["MAX_TRACKING_ENTRY_CAP"] = str(int(max_entry) if max_entry.is_integer() else max_entry)
    settings["MOVE_WINDOW_SECONDS"] = str(int(seconds) if seconds.is_integer() else seconds)
    settings["DISCORD_WEBHOOK_MIN_RATING"] = str(int(primary_rating) if primary_rating.is_integer() else primary_rating)
    settings["DISCORD_SECONDARY_MIN_RATING"] = str(int(secondary_rating) if secondary_rating.is_integer() else secondary_rating)
    for name, value in (
        ("AUDIT_MAX_AGE_MINUTES", audit_age),
        ("AUDIT_MIN_PRO_TRADERS", audit_pro_traders),
        ("AUDIT_MIN_MARKET_CAP", audit_market_cap),
        ("AUDIT_MIN_GLOBAL_FEES_SOL", audit_fees),
        ("AUDIT_MAX_TOP_10_PERCENT", audit_top_ten),
        ("AUDIT_MAX_DEV_HOLDING_PERCENT", audit_developer),
        ("AUDIT_MAX_SNIPER_PERCENT", audit_snipers),
    ):
        settings[name] = str(int(value) if value.is_integer() else value)
    settings["AUDIT_REQUIRE_TWITTER"] = "true" if settings["AUDIT_REQUIRE_TWITTER"].lower() == "true" else "false"
    settings["AUDIT_REQUIRE_REVOKED_AUTHORITIES"] = "true" if settings["AUDIT_REQUIRE_REVOKED_AUTHORITIES"].lower() == "true" else "false"
    settings["GREEN_CANDLE_PERCENT"] = str(int(green_candle_percent) if green_candle_percent.is_integer() else green_candle_percent)
    settings["EARLY_MOMENTUM_PERCENT"] = str(int(early_momentum_percent) if early_momentum_percent.is_integer() else early_momentum_percent)
    settings["EARLY_MOMENTUM_WINDOW_SECONDS"] = str(int(early_momentum_window) if early_momentum_window.is_integer() else early_momentum_window)
    settings["EARLY_MOMENTUM_HOLD_SECONDS"] = str(int(early_momentum_hold) if early_momentum_hold.is_integer() else early_momentum_hold)

    current = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    found = set()
    lines = []
    for line in current.splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in settings:
            name = match.group(1)
            found.add(name)
            lines.append(f"{name}={settings[name]}")
        else:
            lines.append(line)

    for name in SETTING_DEFAULTS:
        if name not in found:
            lines.append(f"{name}={settings[name]}")
    ENV_FILE.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"ok": True, "settings": settings, "credentialsReady": credentials_ready()}


def emit(event_type, payload):
    global event_number
    with lock:
        if event_type == "status":
            monitor_status.update(payload)
        event_number += 1
        events.append({"id": event_number, "type": event_type, "payload": payload})
        del events[:-500]


def public_state():
    settings = read_settings()
    with lock:
        current_status = monitor_status.copy()
        current_coins = list(tracked_coins.values())
    return {
        "status": current_status,
        "movement": {
            "startMarketCap": settings["START_MARKET_CAP"],
            "targetMarketCap": settings["TARGET_MARKET_CAP"],
            "maxTrackingEntryCap": settings["MAX_TRACKING_ENTRY_CAP"],
            "windowSeconds": settings["MOVE_WINDOW_SECONDS"],
        },
        "audit": {
            "maxAgeMinutes": settings["AUDIT_MAX_AGE_MINUTES"],
            "minProTraders": settings["AUDIT_MIN_PRO_TRADERS"],
            "minMarketCap": settings["AUDIT_MIN_MARKET_CAP"],
            "minGlobalFeesSol": settings["AUDIT_MIN_GLOBAL_FEES_SOL"],
            "requireTwitter": settings["AUDIT_REQUIRE_TWITTER"].lower() == "true",
            "maxTopTenPercent": settings["AUDIT_MAX_TOP_10_PERCENT"],
            "maxDeveloperPercent": settings["AUDIT_MAX_DEV_HOLDING_PERCENT"],
            "maxSniperPercent": settings["AUDIT_MAX_SNIPER_PERCENT"],
            "requireRevokedAuthorities": settings["AUDIT_REQUIRE_REVOKED_AUTHORITIES"].lower() == "true",
        },
        "trackedCoins": current_coins,
    }


def update_discord_status(online):
    settings = read_settings()
    token = settings["DISCORD_BOT_TOKEN"]
    channel_id = settings["DISCORD_STATUS_CHANNEL_ID"]
    if not token or not channel_id:
        return

    label = "ONLINE" if online else "OFFLINE"
    payload = {
        "embeds": [
            {
                "title": f"Axiom Alerts • {label}",
                "description": (
                    "The market-cap monitor and Discord commands are connected."
                    if online
                    else "The market-cap monitor is stopped."
                ),
                "color": 0x62E6A7 if online else 0xFF6B73,
                "fields": [{"name": "Status", "value": f"● {label}", "inline": True}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Axiom Discord Alerts"},
            }
        ]
    }
    headers = {"Authorization": f"Bot {token}"}
    saved = {}
    if STATUS_FILE.exists():
        saved = json.loads(STATUS_FILE.read_text(encoding="utf-8"))

    response = None
    if saved.get("channelId") == channel_id and saved.get("messageId"):
        response = requests.patch(
            f"https://discord.com/api/v10/channels/{channel_id}/messages/{saved['messageId']}",
            headers=headers,
            json=payload,
            timeout=15,
        )
    if response is None or response.status_code == 404:
        response = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        STATUS_FILE.write_text(
            json.dumps({"channelId": channel_id, "messageId": response.json()["id"]}),
            encoding="utf-8",
        )
    else:
        response.raise_for_status()


def queue_discord_status(online):
    threading.Thread(target=update_discord_status, args=(online,), daemon=True).start()


def log_line(line):
    message = line.strip()
    if not message:
        return

    alert_match = re.search(r"ALERT_EVENT (\{.+\})$", message)
    if alert_match:
        payload = json.loads(alert_match.group(1))
        with lock:
            tracked_coins.pop(payload["address"], None)
        emit("alert", payload)
        return

    tracking_match = re.search(r"TRACKING_EVENT (\{.+\})$", message)
    if tracking_match:
        payload = json.loads(tracking_match.group(1))
        with lock:
            if payload["action"] == "remove":
                tracked_coins.pop(payload["address"], None)
            else:
                tracked_coins[payload["address"]] = payload
        emit("tracking", payload)
        return

    level = "info"
    if re.search(r"error|failed|exception", message, re.IGNORECASE):
        level = "error"
    elif re.search(r"warning|reconnecting", message, re.IGNORECASE):
        level = "warning"
    if re.search(r"Watching Axiom", message, re.IGNORECASE):
        level = "success"
        emit("status", {"state": "running", "label": "Connected"})
        queue_discord_status(True)
    if re.search(r"Alerted .+: \$", message, re.IGNORECASE):
        level = "alert"

    clean_message = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?\s+(?:-\s+)?", "", message)
    clean_message = re.sub(r"^(?:AxiomTradeWebSocket\s+-\s+)?(?:INFO|WARNING|ERROR)\s+-?\s*", "", clean_message)
    clean_message = clean_message.replace("�", "")
    emit("log", {"level": level, "message": clean_message, "time": "Now"})


def pipe_output(stream):
    for line in iter(stream.readline, ""):
        log_line(line)


def wait_for_bot(process):
    global bot_process, stopping
    code = process.wait()
    with lock:
        if bot_process is not process:
            return
        bot_process = None
        expected = stopping
        stopping = False
        tracked_coins.clear()
    emit(
        "status",
        {
            "state": "stopped" if expected else "error",
            "label": "Stopped" if expected else f"Stopped unexpectedly ({code})",
        },
    )
    queue_discord_status(False)


def start_bot():
    global bot_process, stopping
    if bot_process:
        return {"ok": True}
    if not credentials_ready():
        return {"ok": False, "error": "Open Settings and add your Discord and Axiom credentials."}

    stopping = False
    with lock:
        tracked_coins.clear()
    emit("status", {"state": "starting", "label": "Connecting"})
    env = os.environ.copy()
    env.update({"AXIOM_ENV_FILE": str(ENV_FILE), "AXIOM_DATA_DIR": str(APP_DIR), "PYTHONUNBUFFERED": "1"})
    bot_process = subprocess.Popen(
        [sys.executable, str(APP_DIR / "bot.py")],
        cwd=APP_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=pipe_output, args=(bot_process.stdout,), daemon=True).start()
    threading.Thread(target=pipe_output, args=(bot_process.stderr,), daemon=True).start()
    threading.Thread(target=wait_for_bot, args=(bot_process,), daemon=True).start()
    return {"ok": True}


def stop_bot():
    global stopping
    if not bot_process:
        with lock:
            tracked_coins.clear()
        emit("status", {"state": "stopped", "label": "Stopped"})
        update_discord_status(False)
        return
    stopping = True
    emit("status", {"state": "stopping", "label": "Stopping"})
    update_discord_status(False)
    bot_process.terminate()


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def send_json(self, value, status=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_public_json(self, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin in PUBLIC_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, file_path):
        content_types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2"}
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/public/state":
            self.send_public_json(public_state())
            return
        if path == "/api/public/events":
            after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            with lock:
                pending = [
                    event for event in events
                    if event["id"] > after and event["type"] in {"status", "tracking", "alert"}
                ]
            self.send_public_json(pending)
            return
        if path == "/api/state":
            self.send_json({"running": bool(bot_process), "credentialsReady": credentials_ready()})
            return
        if path == "/api/settings":
            self.send_json(read_settings())
            return
        if path == "/api/events":
            after = int(urlparse(self.path).query.replace("after=", "") or 0)
            with lock:
                pending = [event for event in events if event["id"] > after]
            self.send_json(pending)
            return

        if path == "/":
            file_path = RENDERER_DIR / "index.html"
        elif path.startswith("/node_modules/@fortawesome/fontawesome-free/"):
            file_path = FONTAWESOME_DIR / path.removeprefix("/node_modules/@fortawesome/fontawesome-free/")
        else:
            file_path = RENDERER_DIR / path.lstrip("/")

        if file_path.is_file() and (file_path.is_relative_to(RENDERER_DIR) or file_path.is_relative_to(FONTAWESOME_DIR)):
            self.send_file(file_path)
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if path.startswith("/api/public/") and origin in PUBLIC_ORIGINS:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()
            return
        self.send_error(403)

    def do_POST(self):
        global server
        length = int(self.headers.get("Content-Length", 0))
        values = json.loads(self.rfile.read(length) or b"{}")
        path = urlparse(self.path).path
        if path == "/api/start":
            self.send_json(start_bot())
        elif path == "/api/stop":
            stop_bot()
            self.send_json({"ok": True})
        elif path == "/api/settings":
            try:
                self.send_json(save_settings(values))
            except ValueError:
                self.send_json({"ok": False, "error": "Market caps and movement time must be valid numbers."})
        elif path == "/api/shutdown":
            stop_bot()
            self.send_json({"ok": True})
            threading.Thread(target=server.shutdown, daemon=True).start()
        else:
            self.send_error(404)


def main():
    global server
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"Axiom Alerts is running at {url}")
    print("Use the red close button in the app or close this window to stop it.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_bot()
        server.server_close()


if __name__ == "__main__":
    main()
