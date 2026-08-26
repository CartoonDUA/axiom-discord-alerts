const API_URL = "http://127.0.0.1:8765";
const tracked = new Map();
let lastEvent = 0;
let connected = false;

const connectionPill = document.getElementById("connectionPill");
const connectionText = document.getElementById("connectionText");
const offlineNotice = document.getElementById("offlineNotice");
const trackedCoins = document.getElementById("trackedCoins");
const eventStream = document.getElementById("eventStream");

function formatCap(value) {
  const amount = Number(value);
  if (amount >= 1_000_000) return `$${Number((amount / 1_000_000).toFixed(1))}M`;
  if (amount >= 1_000) return `$${Number((amount / 1_000).toFixed(1))}K`;
  return `$${amount.toLocaleString()}`;
}

function localTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function request(path) {
  const response = await fetch(`${API_URL}${path}`, {
    mode: "cors",
    cache: "no-store",
    targetAddressSpace: "loopback",
  });
  if (!response.ok) throw new Error(`Local backend returned ${response.status}`);
  return response.json();
}

function setConnection(isConnected) {
  connected = isConnected;
  connectionPill.className = `connection-pill ${isConnected ? "connected" : "offline"}`;
  connectionText.textContent = isConnected ? "Connected to this PC" : "Local app offline";
  offlineNotice.hidden = isConnected;
  if (!isConnected) document.getElementById("monitorStatus").textContent = "Backend offline";
}

function renderMovement(movement) {
  const start = Number(movement.startMarketCap);
  const target = Number(movement.targetMarketCap);
  const seconds = Number(movement.windowSeconds);
  const max = target * 1.2;
  const startPosition = Math.max(4, Math.min(90, (start / max) * 100));
  const endPosition = Math.max(startPosition + 4, Math.min(96, (target / max) * 100));

  document.getElementById("startCap").textContent = formatCap(start);
  document.getElementById("targetCap").textContent = formatCap(target);
  document.getElementById("moveWindow").textContent = `${seconds}s`;
  document.getElementById("movementSentence").textContent =
    `Track from ${formatCap(start)}, ignore entries above ${formatCap(movement.maxTrackingEntryCap)}, and alert at ${formatCap(target)} within ${seconds} seconds.`;
  document.getElementById("rangeStart").style.left = `${startPosition}%`;
  document.getElementById("rangeEnd").style.left = `${endPosition}%`;
  document.getElementById("rangeFill").style.left = `${startPosition}%`;
  document.getElementById("rangeFill").style.right = `${100 - endPosition}%`;
}

function renderAudit(audit) {
  document.getElementById("maxAge").textContent = `≤ ${audit.maxAgeMinutes} min`;
  document.getElementById("proTraders").textContent = `≥ ${audit.minProTraders}`;
  document.getElementById("minMarketCap").textContent = `≥ ${formatCap(audit.minMarketCap)}`;
  document.getElementById("globalFees").textContent = `≥ ${audit.minGlobalFeesSol} SOL`;
  document.getElementById("maxTopTen").textContent = `≤ ${audit.maxTopTenPercent}%`;
  document.getElementById("maxDeveloper").textContent = `≤ ${audit.maxDeveloperPercent}%`;
  document.getElementById("maxSnipers").textContent = `≤ ${audit.maxSniperPercent}%`;
  const twitter = document.getElementById("twitterRequired");
  twitter.textContent = audit.requireTwitter ? "Required" : "Not required";
  twitter.className = audit.requireTwitter ? "enabled" : "";
  const authorities = document.getElementById("authoritiesRequired");
  authorities.textContent = audit.requireRevokedAuthorities ? "Must be revoked" : "Not required";
  authorities.className = audit.requireRevokedAuthorities ? "enabled" : "";
}

function coinCard(coin) {
  const card = document.createElement("article");
  card.className = "coin-card";

  const icon = document.createElement("span");
  icon.className = "coin-icon";
  icon.innerHTML = '<i class="fa-solid fa-chart-line"></i>';

  const name = document.createElement("div");
  name.className = "coin-name";
  const title = document.createElement("strong");
  title.textContent = `${coin.name} · $${String(coin.ticker).replace(/^\$/, "")}`;
  const meta = document.createElement("span");
  meta.textContent = `${coin.elapsed || 0}s elapsed · ${coin.address.slice(0, 6)}…${coin.address.slice(-4)}`;
  name.append(title, meta);

  const actions = document.createElement("div");
  actions.className = "coin-actions";
  const open = document.createElement("a");
  open.href = `https://axiom.trade/t/${coin.address}`;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.title = "Open in Axiom";
  open.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square"></i>';
  const copy = document.createElement("button");
  copy.type = "button";
  copy.title = "Copy coin address";
  copy.innerHTML = '<i class="fa-regular fa-copy"></i>';
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(coin.address);
    copy.innerHTML = '<i class="fa-solid fa-check"></i>';
    setTimeout(() => { copy.innerHTML = '<i class="fa-regular fa-copy"></i>'; }, 1200);
  });
  actions.append(open, copy);

  const progress = document.createElement("div");
  progress.className = "coin-progress";
  const percent = Math.max(0, Math.min(100, (Number(coin.marketCap) / Number(coin.targetCap)) * 100));
  const progressLabel = document.createElement("div");
  progressLabel.className = "coin-progress-label";
  const currentCap = document.createElement("span");
  currentCap.textContent = formatCap(coin.marketCap);
  const targetCap = document.createElement("span");
  targetCap.textContent = `${formatCap(coin.targetCap)} target`;
  progressLabel.append(currentCap, targetCap);
  const progressTrack = document.createElement("div");
  progressTrack.className = "progress-track";
  const progressFill = document.createElement("span");
  progressFill.style.width = `${percent}%`;
  progressTrack.append(progressFill);
  progress.append(progressLabel, progressTrack);

  card.append(icon, name, actions, progress);
  return card;
}

function renderTracked() {
  document.getElementById("trackedCount").textContent = String(tracked.size);
  trackedCoins.replaceChildren();
  if (!tracked.size) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML =
      '<i class="fa-solid fa-crosshairs"></i><strong>No active movement yet</strong>' +
      '<span>Coins appear here after passing every audit filter and crossing the starting market cap.</span>';
    trackedCoins.append(empty);
    return;
  }
  [...tracked.values()]
    .sort((a, b) => Number(b.marketCap) - Number(a.marketCap))
    .forEach((coin) => trackedCoins.append(coinCard(coin)));
}

function addEvent(type, message, detail = "") {
  eventStream.querySelector(".empty-event")?.remove();
  const row = document.createElement("div");
  row.className = `event-row ${type}`;
  const icons = {
    start: "fa-crosshairs",
    remove: "fa-hourglass-end",
    alert: "fa-bolt",
    status: "fa-signal",
  };
  row.innerHTML =
    `<time>${localTime()}</time><span class="event-icon"><i class="fa-solid ${icons[type] || icons.status}"></i></span>` +
    `<strong></strong><span></span>`;
  row.querySelector("strong").textContent = message;
  row.querySelector("span:last-child").textContent = detail;
  eventStream.append(row);
  while (eventStream.children.length > 80) eventStream.firstElementChild.remove();
  eventStream.scrollTop = eventStream.scrollHeight;
  document.getElementById("lastUpdated").textContent = `Updated ${localTime()}`;
}

function applyStatus(status, showEvent = false) {
  document.getElementById("monitorStatus").textContent = status.label;
  if (showEvent) addEvent("status", `Monitor ${status.label.toLowerCase()}`);
  if (status.state === "stopped" || status.state === "error") {
    tracked.clear();
    renderTracked();
  }
}

function applyTracking(coin, showEvent = true) {
  if (coin.action === "remove") {
    tracked.delete(coin.address);
    if (showEvent) addEvent("remove", `Stopped tracking $${String(coin.ticker).replace(/^\$/, "")}`, formatCap(coin.marketCap));
  } else {
    tracked.set(coin.address, coin);
    if (showEvent && coin.action === "start") {
      addEvent("start", `Tracking $${String(coin.ticker).replace(/^\$/, "")}`, `${formatCap(coin.marketCap)} → ${formatCap(coin.targetCap)}`);
    }
  }
  renderTracked();
}

function applyAlert(alert) {
  tracked.delete(alert.address);
  renderTracked();
  addEvent("alert", `$${String(alert.ticker).replace(/^\$/, "")} completed the move`, `${formatCap(alert.marketCap)} in ${alert.elapsed}s · ${alert.rugRating}/10 risk`);
}

async function refreshState() {
  try {
    const state = await request("/api/public/state");
    setConnection(true);
    renderMovement(state.movement);
    renderAudit(state.audit);
    applyStatus(state.status);
    tracked.clear();
    state.trackedCoins.forEach((coin) => tracked.set(coin.address, coin));
    renderTracked();
  } catch {
    setConnection(false);
  }
}

async function pollEvents() {
  try {
    const events = await request(`/api/public/events?after=${lastEvent}`);
    setConnection(true);
    for (const event of events) {
      lastEvent = event.id;
      if (event.type === "status") applyStatus(event.payload, true);
      if (event.type === "tracking") applyTracking(event.payload);
      if (event.type === "alert") applyAlert(event.payload);
    }
  } catch {
    setConnection(false);
  }
  setTimeout(pollEvents, connected ? 600 : 2500);
}

document.getElementById("retryButton").addEventListener("click", refreshState);
refreshState();
pollEvents();
setInterval(refreshState, 3000);
