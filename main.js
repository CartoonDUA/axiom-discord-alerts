const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow;
let botProcess;
let stopping = false;

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

function credentialsReady() {
  const envFile = runtimePaths().env;
  if (!fs.existsSync(envFile)) return false;

  const contents = fs.readFileSync(envFile, "utf8");
  return ["DISCORD_WEBHOOK_URL", "AXIOM_ACCESS_TOKEN", "AXIOM_REFRESH_TOKEN"].every(
    (name) => new RegExp(`^${name}=.+$`, "m").test(contents),
  );
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
  if (/Alerted .+ at \$/i.test(message)) {
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
    return { ok: false, error: "Add all three credentials to .env before starting." };
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
ipcMain.on("window:minimize", () => mainWindow?.minimize());
ipcMain.on("window:close", () => mainWindow?.close());
ipcMain.on("open:url", (_, url) => {
  if (url === "https://axiom.trade/") shell.openExternal(url);
});

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
app.on("before-quit", stopBot);
