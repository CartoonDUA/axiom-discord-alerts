const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const statusPill = document.getElementById("statusPill");
const statusText = document.getElementById("statusText");
const uptime = document.getElementById("uptime");
const alertCount = document.getElementById("alertCount");
const credentialStatus = document.getElementById("credentialStatus");
const activityList = document.getElementById("activityList");

let startedAt = null;
let timer = null;
let alerts = 0;

const icons = {
  info: "fa-circle-info",
  success: "fa-circle-check",
  warning: "fa-triangle-exclamation",
  error: "fa-circle-xmark",
  alert: "fa-bell",
};

function setStatus(state, label) {
  statusPill.className = `status-pill ${state}`;
  statusText.textContent = label;

  const active = state === "starting" || state === "running" || state === "stopping";
  startButton.disabled = active;
  stopButton.disabled = !active;

  if (state === "running" && !startedAt) {
    startedAt = Date.now();
    timer = setInterval(updateUptime, 1000);
  }

  if ((state === "stopped" || state === "error") && timer) {
    clearInterval(timer);
    timer = null;
    startedAt = null;
  }
}

function updateUptime() {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const remaining = String(seconds % 60).padStart(2, "0");
  uptime.textContent = `${hours}:${minutes}:${remaining}`;
}

function addLog(entry) {
  document.getElementById("emptyState")?.remove();
  const row = document.createElement("div");
  row.className = `log-row ${entry.level}`;

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = entry.time;

  const icon = document.createElement("i");
  icon.className = `fa-solid ${icons[entry.level] || icons.info} log-icon`;

  const message = document.createElement("span");
  message.className = "log-message";
  message.textContent = entry.message;
  message.title = entry.message;

  row.append(time, icon, message);
  activityList.append(row);
  activityList.scrollTop = activityList.scrollHeight;
}

startButton.addEventListener("click", async () => {
  const result = await window.axiom.start();
  if (!result.ok) {
    setStatus("error", "Setup required");
    addLog({ level: "error", message: result.error, time: "Now" });
  }
});

stopButton.addEventListener("click", () => window.axiom.stop());
document.getElementById("closeWindow").addEventListener("click", () => window.axiom.close());
document.getElementById("minimizeWindow").addEventListener("click", () => window.axiom.minimize());
document.getElementById("openAxiom").addEventListener("click", () => window.axiom.openAxiom());
document.getElementById("clearActivity").addEventListener("click", () => {
  activityList.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.id = "emptyState";
  empty.innerHTML = '<div><i class="fa-solid fa-signal"></i></div><p>Activity cleared.</p>';
  activityList.append(empty);
});

window.axiom.onStatus(({ state, label }) => setStatus(state, label));
window.axiom.onLog(addLog);
window.axiom.onAlert(() => {
  alerts += 1;
  alertCount.textContent = String(alerts);
});

window.axiom.state().then((state) => {
  credentialStatus.textContent = state.credentialsReady ? "Credentials ready" : "Setup required";
  credentialStatus.style.color = state.credentialsReady ? "#62e6a7" : "#ff8d94";
  setStatus(state.running ? "running" : "stopped", state.running ? "Connected" : "Stopped");
});
