if (!window.axiom) {
  const listeners = { status: [], log: [], alert: [] };
  let lastEvent = 0;
  let polling = true;

  async function request(path, options) {
    const response = await fetch(path, options);
    return response.json();
  }

  async function post(path, value = {}) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value),
    });
  }

  async function pollEvents() {
    while (polling) {
      const events = await request(`/api/events?after=${lastEvent}`);
      for (const event of events) {
        lastEvent = event.id;
        listeners[event.type].forEach((callback) => callback(event.payload));
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  window.axiom = {
    start: () => post("/api/start"),
    stop: () => post("/api/stop"),
    state: () => request("/api/state"),
    getSettings: () => request("/api/settings"),
    saveSettings: (settings) => post("/api/settings", settings),
    minimize: () => window.blur(),
    close: async () => {
      polling = false;
      await post("/api/shutdown");
      window.close();
    },
    openAxiom: () => window.open("https://axiom.trade/", "_blank", "noopener"),
    openCoin: (address) => window.open(`https://axiom.trade/t/${address}`, "_blank", "noopener"),
    copyCoin: async (address) => {
      await navigator.clipboard.writeText(address);
      return true;
    },
    onStatus: (callback) => listeners.status.push(callback),
    onLog: (callback) => listeners.log.push(callback),
    onAlert: (callback) => listeners.alert.push(callback),
  };

  pollEvents();
}
