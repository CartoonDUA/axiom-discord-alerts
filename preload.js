const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("axiom", {
  start: () => ipcRenderer.invoke("bot:start"),
  stop: () => ipcRenderer.invoke("bot:stop"),
  state: () => ipcRenderer.invoke("bot:state"),
  minimize: () => ipcRenderer.send("window:minimize"),
  close: () => ipcRenderer.send("window:close"),
  openAxiom: () => ipcRenderer.send("open:url", "https://axiom.trade/"),
  onStatus: (callback) => ipcRenderer.on("bot-status", (_, value) => callback(value)),
  onLog: (callback) => ipcRenderer.on("bot-log", (_, value) => callback(value)),
  onAlert: (callback) => ipcRenderer.on("bot-alert", callback),
});
