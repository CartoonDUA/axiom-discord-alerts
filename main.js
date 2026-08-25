const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow;
let botProcess;
let stopping = false;

const settingDefaults = {
  DISCORD_WEBHOOK_URL: "",
  AXIOM_ACCESS_TOKEN: "",
  AXIOM_REFRESH_TOKEN: "",
  CF_CLEARANCE: "",
  START_MARKET_CAP: "5000",
  TARGET_MARKET_CAP: "20000",
  MOVE_WINDOW_SECONDS: "40",
};

function localDataDir() {
  if (app.isPackaged) {
    return process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(process.execPath);
  }
  return __dirname;
}

function runtimePaths() {
  const resources = app.isPackaged ? process.resourcesPath : __dirname;
  const pythonFolder = app.isPackaged ? "python" : ".venv";

  return {
    python: path.join(resources, pythonFolder, "Scripts", "python.exe"),
    bot: path.join(resources, "bot.py"),
    env: path.join(localDataDir(), ".env"),
    data: localDataDir(),
  };
}

function readSettings() {
  const envFile = runtimePaths().env;
  const settings = { ...settingDefaults };
  if (!fs.existsSync(envFile)) return settings;

  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match || !(match[1] in settings)) continue;

    let value = match[2].trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    settings[match[1]] = value;
  }

  return settings;
}

function writeSettings(settings) {
  const envFile = runtimePaths().env;
  const current = fs.existsSync(envFile) ? fs.readFileSync(envFile, "utf8") : "";
  const found = new Set();
  const lines = current.split(/\r?\n/).map((line) => {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=/);
    if (!match || !(match[1] in settings)) return line;
    found.add(match[1]);
    return `${match[1]}=${settings[match[1]]}`;
  });

  for (const name of Object.keys(settingDefaults)) {
    if (!found.has(name)) lines.push(`${name}=${settings[name]}`);
  }

  fs.writeFileSync(envFile, `${lines.filter((line, index) => line || index < lines.length - 1).join("\n").trim()}\n`, "utf8");
}

function credentialsReady() {
  const settings = readSettings();

  return ["DISCORD_WEBHOOK_URL", "AXIOM_ACCESS_TOKEN", "AXIOM_REFRESH_TOKEN"].every(
    (name) => settings[name].length > 0,
  );
}

function saveSettings(values) {
  if (botProcess) {
    return { ok: false, error: "Stop the monitor before changing settings." };
  }

  const settings = {};
  for (const [name, fallback] of Object.entries(settingDefaults)) {
    const value = typeof values?.[name] === "string" ? values[name].trim() : fallback;
    settings[name] = value.replace(/[\r\n]/g, "");
  }

  const start = Number(settings.START_MARKET_CAP);
  const target = Number(settings.TARGET_MARKET_CAP);
  const seconds = Number(settings.MOVE_WINDOW_SECONDS);
  if (!Number.isFinite(start) || start <= 0) {
    return { ok: false, error: "Starting market cap must be above zero." };
  }
  if (!Number.isFinite(target) || target <= start) {
    return { ok: false, error: "Target market cap must be above the starting cap." };
  }
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return { ok: false, error: "Movement window must be above zero seconds." };
  }

  settings.START_MARKET_CAP = String(start);
  settings.TARGET_MARKET_CAP = String(target);
  settings.MOVE_WINDOW_SECONDS = String(seconds);
  writeSettings(settings);
  return { ok: true, settings, credentialsReady: credentialsReady() };
}

function emit(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function logLine(line) {
  const message = line.trim();
  if (!message) return;

  let level = "info";
  if (/error|failed|exception/i.test(message)) level = "error";
  if (/warning|reconnecting/i.test(message)) level = "warning";
  if (/Watching Axiom/i.test(message)) {
    level = "success";
    emit("bot-status", { state: "running", label: "Connected" });
  }
  if (/Alerted .+: \$/i.test(message)) {
    level = "alert";
    emit("bot-alert");
  }

  emit("bot-log", {
    level,
    message: message
      .replace(/�/g, "")
      .replace(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?\s+(?:-\s+)?/, "")
      .replace(/^(?:AxiomTradeWebSocket\s+-\s+)?(?:INFO|WARNING|ERROR)\s+-?\s*/, ""),
    time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  });
}

function pipeLines(stream) {
  let pending = "";
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    pending += chunk;
    const lines = pending.split(/\r?\n/);
    pending = lines.pop();
    lines.forEach(logLine);
  });
}

function startBot() {
  if (botProcess) return { ok: true };
  if (!credentialsReady()) {
    return { ok: false, error: "Open Settings and add your Discord and Axiom credentials." };
  }

  const paths = runtimePaths();
  if (!fs.existsSync(paths.python) || !fs.existsSync(paths.bot)) {
    return { ok: false, error: "The Python bot runtime could not be found." };
  }

  stopping = false;
  emit("bot-status", { state: "starting", label: "Connecting" });
  botProcess = spawn(paths.python, [paths.bot], {
    cwd: paths.data,
    windowsHide: true,
    env: {
      ...process.env,
      AXIOM_ENV_FILE: paths.env,
      AXIOM_DATA_DIR: paths.data,
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  pipeLines(botProcess.stdout);
  pipeLines(botProcess.stderr);

  botProcess.on("error", (error) => {
    logLine(`ERROR ${error.message}`);
  });

  botProcess.on("exit", (code) => {
    botProcess = null;
    const expected = stopping;
    stopping = false;
    emit("bot-status", {
      state: expected ? "stopped" : "error",
      label: expected ? "Stopped" : `Stopped unexpectedly (${code ?? "unknown"})`,
    });
  });

  return { ok: true };
}

function stopBot() {
  if (!botProcess) {
    emit("bot-status", { state: "stopped", label: "Stopped" });
    return;
  }

  stopping = true;
  emit("bot-status", { state: "stopping", label: "Stopping" });
  botProcess.kill();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 760,
    minWidth: 920,
    minHeight: 640,
    frame: false,
    show: false,
    backgroundColor: "#0b0d12",
    icon: path.join(__dirname, "assets", "icon.png"),
    title: "Axiom Alerts",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => {
    stopBot();
    mainWindow = null;
  });
}

ipcMain.handle("bot:start", () => startBot());
ipcMain.handle("bot:stop", () => stopBot());
ipcMain.handle("bot:state", () => ({
  running: Boolean(botProcess),
  credentialsReady: credentialsReady(),
}));
ipcMain.handle("settings:get", () => readSettings());
ipcMain.handle("settings:save", (_, values) => saveSettings(values));
ipcMain.on("window:minimize", () => mainWindow?.minimize());
ipcMain.on("window:close", () => mainWindow?.close());
ipcMain.on("open:url", (_, url) => {
  if (url === "https://axiom.trade/") shell.openExternal(url);
});

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
app.on("before-quit", stopBot);
