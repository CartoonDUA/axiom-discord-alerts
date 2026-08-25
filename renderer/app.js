const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const statusPill = document.getElementById("statusPill");
const statusText = document.getElementById("statusText");
const uptime = document.getElementById("uptime");
const alertCount = document.getElementById("alertCount");
const credentialStatus = document.getElementById("credentialStatus");
const activityList = document.getElementById("activityList");
const settingsModal = document.getElementById("settingsModal");
const settingsForm = document.getElementById("settingsForm");
const settingsMessage = document.getElementById("settingsMessage");
const settingInputs = [...document.querySelectorAll("[data-setting]")];

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

function formatCap(value) {
  const amount = Number(value);
  if (amount >= 1_000_000) return `$${Number((amount / 1_000_000).toFixed(1))}M`;
  if (amount >= 1_000) return `$${Number((amount / 1_000).toFixed(1))}K`;
  return `$${amount.toLocaleString()}`;
}

function showSettingsSummary(settings) {
  const start = Number(settings.START_MARKET_CAP || 5000);
  const target = Number(settings.TARGET_MARKET_CAP || 20000);
  const seconds = Number(settings.MOVE_WINDOW_SECONDS || 40);
  const rangeMax = target * 1.25;
  const startPosition = Math.max(4, Math.min(92, (start / rangeMax) * 100));
  const endPosition = Math.max(startPosition + 3, Math.min(96, (target / rangeMax) * 100));

  document.getElementById("rangeSummary").textContent = `${formatCap(start)} → ${formatCap(target)} · ${seconds}s`;
  document.getElementById("movementDescription").textContent =
    `Alert when a coin moves from ${formatCap(start)} to ${formatCap(target)} within ${seconds} seconds.`;
  document.getElementById("rangeMax").textContent = `${formatCap(rangeMax)}+`;
  document.getElementById("rangeStart").style.left = `${startPosition}%`;
  document.getElementById("rangeEnd").style.left = `${endPosition}%`;
  document.getElementById("rangeFill").style.left = `${startPosition}%`;
  document.getElementById("rangeFill").style.right = `${100 - endPosition}%`;
}

function showCredentialStatus(ready) {
  credentialStatus.textContent = ready ? "Credentials ready" : "Setup required";
  credentialStatus.style.color = ready ? "#62e6a7" : "#ff8d94";
}

async function openSettings() {
  const settings = await window.axiom.getSettings();
  for (const input of settingInputs) {
    if (input.type === "checkbox") input.checked = settings[input.dataset.setting] === "true";
    else input.value = settings[input.dataset.setting] || "";
    if (input.type === "text" && input.closest(".secret-input")) input.type = "password";
  }
  document.querySelectorAll(".reveal-secret i").forEach((icon) => {
    icon.className = "fa-regular fa-eye";
  });
  settingsMessage.className = "";
  settingsMessage.textContent = "Stop the monitor before saving changes.";
  settingsModal.hidden = false;
  settingInputs[0].focus();
}

function closeSettings() {
  settingsModal.hidden = true;
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

function addAlert(alert) {
  document.getElementById("emptyState")?.remove();
  const card = document.createElement("div");
  card.className = "alert-card";

  const details = document.createElement("button");
  details.className = "alert-details";
  details.type = "button";
  details.title = "Open this coin in Axiom";

  const icon = document.createElement("span");
  icon.className = "alert-coin-icon";
  icon.innerHTML = '<i class="fa-solid fa-bolt"></i>';

  const text = document.createElement("span");
  text.className = "alert-text";

  const title = document.createElement("strong");
  title.textContent = `${alert.name} (${alert.ticker})`;

  const meta = document.createElement("span");
  meta.textContent = `${formatCap(alert.marketCap)} in ${alert.elapsed}s · ${alert.address}`;

  text.append(title, meta);
  details.append(icon, text);

  const actions = document.createElement("div");
  actions.className = "alert-actions";

  const openButton = document.createElement("button");
  openButton.className = "alert-action open";
  openButton.type = "button";
  openButton.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i><span>Open in Axiom</span>';

  const copyButton = document.createElement("button");
  copyButton.className = "alert-action";
  copyButton.type = "button";
  copyButton.innerHTML = '<i class="fa-regular fa-copy"></i><span>Copy address</span>';

  const openCoin = () => window.axiom.openCoin(alert.address);
  details.addEventListener("click", openCoin);
  openButton.addEventListener("click", openCoin);
  copyButton.addEventListener("click", async () => {
    if (!(await window.axiom.copyCoin(alert.address))) return;
    copyButton.querySelector("i").className = "fa-solid fa-check";
    copyButton.querySelector("span").textContent = "Copied";
    setTimeout(() => {
      copyButton.querySelector("i").className = "fa-regular fa-copy";
      copyButton.querySelector("span").textContent = "Copy address";
    }, 1500);
  });

  actions.append(openButton, copyButton);
  card.append(details, actions);
  activityList.append(card);
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
document.getElementById("settingsButton").addEventListener("click", openSettings);
document.getElementById("closeSettings").addEventListener("click", closeSettings);
document.getElementById("cancelSettings").addEventListener("click", closeSettings);
settingsModal.addEventListener("click", (event) => {
  if (event.target === settingsModal) closeSettings();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !settingsModal.hidden) closeSettings();
});

document.querySelectorAll(".reveal-secret").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.previousElementSibling;
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    button.querySelector("i").className = `fa-regular ${visible ? "fa-eye" : "fa-eye-slash"}`;
  });
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = Object.fromEntries(
    settingInputs.map((input) => [input.dataset.setting, input.type === "checkbox" ? String(input.checked) : input.value]),
  );
  const result = await window.axiom.saveSettings(settings);

  if (!result.ok) {
    settingsMessage.className = "error";
    settingsMessage.textContent = result.error;
    return;
  }

  settingsMessage.className = "success";
  settingsMessage.textContent = "Saved locally. Your next monitor session will use these settings.";
  showSettingsSummary(result.settings);
  showCredentialStatus(result.credentialsReady);
  addLog({ level: "success", message: "Settings saved locally", time: "Now" });
});
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
window.axiom.onAlert((alert) => {
  alerts += 1;
  alertCount.textContent = String(alerts);
  addAlert(alert);
});

Promise.all([window.axiom.state(), window.axiom.getSettings()]).then(([state, settings]) => {
  showCredentialStatus(state.credentialsReady);
  showSettingsSummary(settings);
  setStatus(state.running ? "running" : "stopped", state.running ? "Connected" : "Stopped");
});
