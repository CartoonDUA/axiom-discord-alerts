import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import webbrowser


APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env"
RENDERER_DIR = APP_DIR / "renderer"
FONTAWESOME_DIR = APP_DIR / "node_modules" / "@fortawesome" / "fontawesome-free"
HOST = "127.0.0.1"
PORT = 8765

SETTING_DEFAULTS = {
    "DISCORD_WEBHOOK_URL": "",
    "DISCORD_ALL_WEBHOOK_URL": "",
    "DISCORD_GREEN_CANDLE_WEBHOOK_URL": "",
    "GREEN_CANDLE_PERCENT": "100",
    "EARLY_MOMENTUM_PERCENT": "10",
    "EARLY_MOMENTUM_WINDOW_SECONDS": "15",
    "DISCORD_WEBHOOK_MIN_RATING": "4",
    "DISCORD_SECONDARY_WEBHOOK_URL": "",
    "DISCORD_SECONDARY_MIN_RATING": "2",
    "DISCORD_BOT_TOKEN": "",
    "DISCORD_GUILD_ID": "",
    "AXIOM_ACCESS_TOKEN": "",
    "AXIOM_REFRESH_TOKEN": "",
    "CF_CLEARANCE": "",
    "START_MARKET_CAP": "5000",
    "TARGET_MARKET_CAP": "20000",
    "MOVE_WINDOW_SECONDS": "40",
    "AUDIT_MAX_AGE_MINUTES": "15",
    "AUDIT_MIN_PRO_TRADERS": "2",
    "AUDIT_MIN_MARKET_CAP": "5000",
    "AUDIT_MIN_GLOBAL_FEES_SOL": "0.2",
    "AUDIT_REQUIRE_TWITTER": "true",
}

bot_process = None
stopping = False
events = []
event_number = 0
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
    seconds = float(settings["MOVE_WINDOW_SECONDS"])
    primary_rating = float(settings["DISCORD_WEBHOOK_MIN_RATING"])
    secondary_rating = float(settings["DISCORD_SECONDARY_MIN_RATING"])
    audit_age = float(settings["AUDIT_MAX_AGE_MINUTES"])
    audit_pro_traders = float(settings["AUDIT_MIN_PRO_TRADERS"])
    audit_market_cap = float(settings["AUDIT_MIN_MARKET_CAP"])
    audit_fees = float(settings["AUDIT_MIN_GLOBAL_FEES_SOL"])
    green_candle_percent = float(settings["GREEN_CANDLE_PERCENT"])
    early_momentum_percent = float(settings["EARLY_MOMENTUM_PERCENT"])
    early_momentum_window = float(settings["EARLY_MOMENTUM_WINDOW_SECONDS"])
    if start <= 0:
        return {"ok": False, "error": "Starting market cap must be above zero."}
    if target <= start:
        return {"ok": False, "error": "Target market cap must be above the starting cap."}
    if seconds <= 0:
        return {"ok": False, "error": "Movement window must be above zero seconds."}
    if not 0 <= primary_rating <= 10 or not 0 <= secondary_rating <= 10:
        return {"ok": False, "error": "Webhook rug ratings must be between 0 and 10."}
    if min(audit_age, audit_pro_traders, audit_market_cap, audit_fees) < 0:
        return {"ok": False, "error": "Audit filter values cannot be negative."}
    if green_candle_percent <= 0:
        return {"ok": False, "error": "Green Candle percentage must be above zero."}
    if early_momentum_percent <= 0 or early_momentum_window <= 0:
        return {"ok": False, "error": "Early momentum values must be above zero."}

    settings["START_MARKET_CAP"] = str(int(start) if start.is_integer() else start)
    settings["TARGET_MARKET_CAP"] = str(int(target) if target.is_integer() else target)
    settings["MOVE_WINDOW_SECONDS"] = str(int(seconds) if seconds.is_integer() else seconds)
    settings["DISCORD_WEBHOOK_MIN_RATING"] = str(int(primary_rating) if primary_rating.is_integer() else primary_rating)
    settings["DISCORD_SECONDARY_MIN_RATING"] = str(int(secondary_rating) if secondary_rating.is_integer() else secondary_rating)
    for name, value in (
        ("AUDIT_MAX_AGE_MINUTES", audit_age),
        ("AUDIT_MIN_PRO_TRADERS", audit_pro_traders),
        ("AUDIT_MIN_MARKET_CAP", audit_market_cap),
        ("AUDIT_MIN_GLOBAL_FEES_SOL", audit_fees),
    ):
        settings[name] = str(int(value) if value.is_integer() else value)
    settings["AUDIT_REQUIRE_TWITTER"] = "true" if settings["AUDIT_REQUIRE_TWITTER"].lower() == "true" else "false"
    settings["GREEN_CANDLE_PERCENT"] = str(int(green_candle_percent) if green_candle_percent.is_integer() else green_candle_percent)
    settings["EARLY_MOMENTUM_PERCENT"] = str(int(early_momentum_percent) if early_momentum_percent.is_integer() else early_momentum_percent)
    settings["EARLY_MOMENTUM_WINDOW_SECONDS"] = str(int(early_momentum_window) if early_momentum_window.is_integer() else early_momentum_window)

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
        event_number += 1
        events.append({"id": event_number, "type": event_type, "payload": payload})
        del events[:-500]


def log_line(line):
    message = line.strip()
    if not message:
        return

    alert_match = re.search(r"ALERT_EVENT (\{.+\})$", message)
    if alert_match:
        emit("alert", json.loads(alert_match.group(1)))
        return

    level = "info"
    if re.search(r"error|failed|exception", message, re.IGNORECASE):
        level = "error"
    elif re.search(r"warning|reconnecting", message, re.IGNORECASE):
        level = "warning"
    if re.search(r"Watching Axiom", message, re.IGNORECASE):
        level = "success"
        emit("status", {"state": "running", "label": "Connected"})
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
    emit(
        "status",
        {
            "state": "stopped" if expected else "error",
            "label": "Stopped" if expected else f"Stopped unexpectedly ({code})",
        },
    )


def start_bot():
    global bot_process, stopping
    if bot_process:
        return {"ok": True}
    if not credentials_ready():
        return {"ok": False, "error": "Open Settings and add your Discord and Axiom credentials."}

    stopping = False
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
        emit("status", {"state": "stopped", "label": "Stopped"})
        return
    stopping = True
    emit("status", {"state": "stopping", "label": "Stopping"})
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

    def send_file(self, file_path):
        content_types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2"}
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
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
