const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("axiom", {
  start: () => ipcRenderer.invoke("bot:start"),
  stop: () => ipcRenderer.invoke("bot:stop"),
  state: () => ipcRenderer.invoke("bot:state"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  minimize: () => ipcRenderer.send("window:minimize"),
  close: () => ipcRenderer.send("window:close"),
  openAxiom: () => ipcRenderer.send("open:url", "https://axiom.trade/"),
  openCoin: (address) => ipcRenderer.send("coin:open", address),
  copyCoin: (address) => ipcRenderer.invoke("coin:copy", address),
  onStatus: (callback) => ipcRenderer.on("bot-status", (_, value) => callback(value)),
  onLog: (callback) => ipcRenderer.on("bot-log", (_, value) => callback(value)),
  onAlert: (callback) => ipcRenderer.on("bot-alert", (_, value) => callback(value)),
});
