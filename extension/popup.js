// Configuration
let BACKEND_URL = "http://localhost:8080"; // Loaded from chrome.storage
const API_KEY = "linkedin-bot-beta-2024"; // Shared API key for beta

// Hardcoded beta credentials
const BETA_USERNAME = "beta";
const BETA_PASSWORD = "tester123";

// DOM elements
const loginScreen = document.getElementById("login-screen");
const mainScreen = document.getElementById("main-screen");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");
const loginError = document.getElementById("login-error");
const syncCookiesBtn = document.getElementById("sync-cookies-btn");
const cookieStatus = document.getElementById("cookie-status");
const runBtn = document.getElementById("run-btn");
const stopBtn = document.getElementById("stop-btn");
const statusBar = document.getElementById("status-bar");
const statusText = document.getElementById("status-text");
const configSection = document.getElementById("config-section");
const lastRunInfo = document.getElementById("last-run-info");
const lastRunTime = document.getElementById("last-run-time");
const lastRunResult = document.getElementById("last-run-result");
const campaignInfo = document.getElementById("campaign-info");
const campaignAccount = document.getElementById("campaign-account");
const campaignPhase = document.getElementById("campaign-phase");
const campaignWindow = document.getElementById("campaign-window");

const dailyConnect = document.getElementById("daily-connect");
const dailyMessage = document.getElementById("daily-message");
const dailyFollowup = document.getElementById("daily-followup");
const accountName = document.getElementById("account-name");
const backendUrl = document.getElementById("backend-url");

// Template elements
const templateFile = document.getElementById("template-file");
const uploadTemplateBtn = document.getElementById("upload-template-btn");
const uploadStatus = document.getElementById("upload-status");

// State
let currentState = "stopped"; // "running" | "enabled" | "stopped"

// Persisted keys in chrome.storage.local
const STORAGE_KEYS = [
  "loggedIn", "backendUrl", "accountName",
  "cachedState", "cachedPhase", "cachedPhaseDetail",
  "cachedTimeWindow", "cachedLastRun",
];

// Init
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get(STORAGE_KEYS, (data) => {
    // Restore backend URL
    if (data.backendUrl) {
      BACKEND_URL = data.backendUrl;
      backendUrl.value = data.backendUrl;
    } else {
      backendUrl.value = BACKEND_URL;
    }

    // Restore account name
    if (data.accountName) {
      accountName.value = data.accountName;
    }

    if (data.loggedIn) {
      showMainScreen();

      // Immediately restore cached state so UI is not blank
      if (data.cachedState) {
        applyState(data.cachedState, data.cachedPhase, data.cachedPhaseDetail, data.cachedTimeWindow);
      }
      if (data.cachedLastRun) {
        lastRunInfo.classList.remove("hidden");
        lastRunTime.textContent = data.cachedLastRun;
      }

      // Then fetch live state from backend (overrides cache)
      fetchStatus();
    }
  });
});

// Backend URL change handler
backendUrl.addEventListener("change", () => {
  let url = backendUrl.value.trim();
  if (url.endsWith("/")) url = url.slice(0, -1);
  BACKEND_URL = url;
  backendUrl.value = url;
  chrome.storage.local.set({ backendUrl: url });
});

// Persist account name on change — also re-fetch status for new account
accountName.addEventListener("change", () => {
  chrome.storage.local.set({ accountName: accountName.value.trim() });
  fetchStatus();
});

// Login
loginBtn.addEventListener("click", () => {
  const user = document.getElementById("username").value.trim();
  const pass = document.getElementById("password").value.trim();

  if (user === BETA_USERNAME && pass === BETA_PASSWORD) {
    chrome.storage.local.set({ loggedIn: true });
    loginError.classList.add("hidden");
    showMainScreen();
    fetchStatus();
  } else {
    loginError.classList.remove("hidden");
  }
});

// Logout
logoutBtn.addEventListener("click", () => {
  chrome.storage.local.set({ loggedIn: false, cachedState: null });
  loginScreen.classList.remove("hidden");
  mainScreen.classList.add("hidden");
});

// Sync Cookies
syncCookiesBtn.addEventListener("click", async () => {
  syncCookiesBtn.disabled = true;
  cookieStatus.textContent = "Extracting cookies + browser storage...";

  try {
    // Step 1: Get all LinkedIn cookies from multiple queries
    const [cookies1, cookies2, cookies3] = await Promise.all([
      new Promise((r) => chrome.cookies.getAll({ url: "https://www.linkedin.com" }, r)),
      new Promise((r) => chrome.cookies.getAll({ url: "https://linkedin.com" }, r)),
      new Promise((r) => chrome.cookies.getAll({ domain: ".linkedin.com" }, r)),
    ]);

    // Deduplicate
    const seen = new Set();
    const cookies = [];
    for (const c of [...(cookies1 || []), ...(cookies2 || []), ...(cookies3 || [])]) {
      const key = `${c.name}|${c.domain}`;
      if (!seen.has(key)) {
        seen.add(key);
        cookies.push(c);
      }
    }

    const hasLiAt = cookies.some((c) => c.name === "li_at");
    if (!hasLiAt) {
      console.warn("WARNING: li_at not found. Cookies:", cookies.map((c) => c.name));
    }

    if (!cookies.length) {
      cookieStatus.textContent = "No LinkedIn cookies found. Make sure you're logged in.";
      cookieStatus.className = "hint error";
      syncCookiesBtn.disabled = false;
      return;
    }

    // Step 2: Extract localStorage and sessionStorage from any open LinkedIn tab
    let browserStorage = null;
    let storageError = null;
    try {
      const tabs = await chrome.tabs.query({ url: "https://www.linkedin.com/*" });
      if (tabs && tabs.length > 0 && chrome.scripting) {
        const linkedInTab = tabs[0];
        console.log(`Found LinkedIn tab: ${linkedInTab.id} - ${linkedInTab.url}`);
        const results = await chrome.scripting.executeScript({
          target: { tabId: linkedInTab.id },
          func: () => {
            const ls = {};
            for (let i = 0; i < localStorage.length; i++) {
              const key = localStorage.key(i);
              ls[key] = localStorage.getItem(key);
            }
            const ss = {};
            for (let i = 0; i < sessionStorage.length; i++) {
              const key = sessionStorage.key(i);
              ss[key] = sessionStorage.getItem(key);
            }
            return { localStorage: ls, sessionStorage: ss };
          },
        });
        if (results && results[0] && results[0].result) {
          browserStorage = results[0].result;
          console.log(
            `Extracted localStorage: ${Object.keys(browserStorage.localStorage).length} keys, ` +
            `sessionStorage: ${Object.keys(browserStorage.sessionStorage).length} keys`
          );
        }
      } else {
        storageError = "No LinkedIn tab open";
        console.warn("No LinkedIn tab found - open linkedin.com in a tab first");
      }
    } catch (e) {
      storageError = e.message;
      console.error("Could not extract browser storage:", e);
    }

    // Step 3: Send cookies + storage to backend
    const payload = {
      cookies: cookies.map((c) => ({
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        secure: c.secure,
        httpOnly: c.httpOnly,
        expirationDate: c.expirationDate,
      })),
      browserStorage: browserStorage,
      account_name: accountName.value.trim(),
    };

    const res = await fetch(`${BACKEND_URL}/api/cookies`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.success) {
      let storageMsg = "";
      if (browserStorage) {
        const lsKeys = Object.keys(browserStorage.localStorage).length;
        storageMsg = ` + ${lsKeys} storage keys`;
      } else if (storageError) {
        storageMsg = ` (storage: ${storageError})`;
      }
      const liAtMsg = hasLiAt ? "" : " (WARNING: li_at missing!)";
      cookieStatus.textContent = `Synced ${cookies.length} cookies${storageMsg}${liAtMsg}`;
      cookieStatus.className = hasLiAt ? "hint success" : "hint error";
    } else {
      cookieStatus.textContent = "Failed to sync: " + (data.error || "Unknown error");
      cookieStatus.className = "hint error";
    }
  } catch (err) {
    cookieStatus.textContent = "Connection failed. Is the backend running?";
    cookieStatus.className = "hint error";
    console.error("Sync error:", err);
  } finally {
    syncCookiesBtn.disabled = false;
  }
});

// Run Bot
runBtn.addEventListener("click", () => {
  const config = {
    daily_connect: parseInt(dailyConnect.value) || 20,
    daily_message: parseInt(dailyMessage.value) || 15,
    daily_followup: parseInt(dailyFollowup.value) || 10,
    account_name: accountName.value.trim(),
  };

  runBtn.disabled = true;
  runBtn.textContent = "Starting...";

  fetch(`${BACKEND_URL}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
    body: JSON.stringify(config),
  })
    .then((res) => res.json())
    .then(() => {
      return fetch(`${BACKEND_URL}/api/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
        body: JSON.stringify({ account_name: accountName.value.trim() }),
      });
    })
    .then((res) => res.json())
    .then((data) => {
      if (data.success) {
        applyState("enabled", null, null, null);
        chrome.storage.local.set({ cachedState: "enabled" });
        // Fetch real status after a moment
        setTimeout(fetchStatus, 2000);
      } else {
        alert("Failed to start: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => {
      alert("Connection failed. Is the backend running?");
    })
    .finally(() => {
      runBtn.disabled = false;
      runBtn.textContent = "Run Bot";
    });
});

// Stop Bot
stopBtn.addEventListener("click", () => {
  stopBtn.disabled = true;
  stopBtn.textContent = "Stopping...";

  fetch(`${BACKEND_URL}/api/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
    body: JSON.stringify({ account_name: accountName.value.trim() }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.success) {
        applyState("stopped", null, null, null);
        chrome.storage.local.set({ cachedState: "stopped", cachedPhase: null, cachedPhaseDetail: null });
      }
    })
    .catch(() => {
      alert("Connection failed.");
    })
    .finally(() => {
      stopBtn.disabled = false;
      stopBtn.textContent = "Stop Bot";
    });
});

// ── Template Upload ─────────────────────────────────────────────────────

function validateTemplate(data) {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return "Template must be a JSON object";
  }

  const required = [
    "outreach_prompt", "followup_1_prompt", "followup_2_prompt",
    "followup_3_prompt", "followup_4_prompt",
  ];
  const allowed = new Set([...required, "description"]);

  const extra = Object.keys(data).filter((k) => !allowed.has(k));
  if (extra.length > 0) {
    return `Unexpected keys: ${extra.join(", ")}. Allowed: ${[...allowed].join(", ")}`;
  }

  const missing = required.filter((k) => !(k in data));
  if (missing.length > 0) return `Missing keys: ${missing.join(", ")}`;

  const badType = required.filter((k) => k in data && typeof data[k] !== "string");
  if (badType.length > 0) return `These must be strings: ${badType.join(", ")}`;

  const empty = required.filter((k) => k in data && typeof data[k] === "string" && !data[k].trim());
  if (empty.length > 0) return `These are empty: ${empty.join(", ")}`;

  return null;
}

uploadTemplateBtn.addEventListener("click", () => {
  templateFile.click();
});

templateFile.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  try {
    const text = await file.text();
    const templateData = JSON.parse(text);

    const validationError = validateTemplate(templateData);
    if (validationError) {
      uploadStatus.textContent = `Invalid: ${validationError}`;
      uploadStatus.className = "hint error";
      uploadStatus.classList.remove("hidden");
      templateFile.value = "";
      return;
    }

    uploadTemplateBtn.disabled = true;
    uploadTemplateBtn.textContent = "Uploading...";
    uploadStatus.classList.add("hidden");

    const res = await fetch(`${BACKEND_URL}/api/templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
      body: JSON.stringify(templateData),
    });
    const result = await res.json();

    if (result.success) {
      uploadStatus.textContent = `Saved as ${result.filename}. Use "${result.template_name}" in Attio bot_inputs prompt_template column.`;
      uploadStatus.className = "hint success";
    } else {
      uploadStatus.textContent = "Failed: " + (result.error || "Unknown error");
      uploadStatus.className = "hint error";
    }
    uploadStatus.classList.remove("hidden");
  } catch (err) {
    if (err instanceof SyntaxError) {
      uploadStatus.textContent = "Invalid JSON file. Check the format.";
    } else {
      uploadStatus.textContent = "Upload error: " + err.message;
    }
    uploadStatus.className = "hint error";
    uploadStatus.classList.remove("hidden");
  } finally {
    uploadTemplateBtn.disabled = false;
    uploadTemplateBtn.textContent = "Upload New Template";
    templateFile.value = "";
  }
});

// ── Helpers ──────────────────────────────────────────────────────────────

function showMainScreen() {
  loginScreen.classList.add("hidden");
  mainScreen.classList.remove("hidden");
}

function applyState(state, phase, phaseDetail, timeWindow) {
  currentState = state;

  if (state === "running") {
    statusBar.className = "status-bar status-running";
    const phaseStr = phase ? ` — ${phase}` : "";
    statusText.textContent = `Running${phaseStr}`;
    runBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");
    setConfigDisabled(true);
  } else if (state === "enabled") {
    statusBar.className = "status-bar status-enabled";
    statusText.textContent = "Enabled (waiting for next cycle)";
    runBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");
    setConfigDisabled(true);
  } else {
    statusBar.className = "status-bar status-stopped";
    statusText.textContent = "Stopped";
    runBtn.classList.remove("hidden");
    stopBtn.classList.add("hidden");
    setConfigDisabled(false);
  }

  // Campaign info panel
  const acct = accountName.value.trim();
  if (state !== "stopped" && acct) {
    campaignInfo.classList.remove("hidden");
    campaignAccount.textContent = acct;
    campaignPhase.textContent = phase
      ? `${phase}${phaseDetail ? " — " + phaseDetail : ""}`
      : (state === "enabled" ? "Scheduled" : "-");
    campaignWindow.textContent = timeWindow || "-";
  } else if (state === "stopped") {
    campaignInfo.classList.add("hidden");
  }
}

function setConfigDisabled(disabled) {
  dailyConnect.disabled = disabled;
  dailyMessage.disabled = disabled;
  dailyFollowup.disabled = disabled;
  accountName.disabled = disabled;
}

function fetchStatus() {
  const acct = accountName.value.trim();
  const url = acct
    ? `${BACKEND_URL}/api/status?account_name=${encodeURIComponent(acct)}`
    : `${BACKEND_URL}/api/status`;

  fetch(url, {
    headers: { "X-Api-Key": API_KEY },
  })
    .then((res) => res.json())
    .then((data) => {
      const state = data.state || (data.running ? "running" : "stopped");
      applyState(state, data.phase, data.phase_detail, data.time_window);

      // Restore config from backend if available
      if (data.config) {
        if (data.config.daily_connect) dailyConnect.value = data.config.daily_connect;
        if (data.config.daily_message) dailyMessage.value = data.config.daily_message;
        if (data.config.daily_followup) dailyFollowup.value = data.config.daily_followup;
      }

      // Last run info
      if (data.last_run) {
        lastRunInfo.classList.remove("hidden");
        lastRunTime.textContent = data.last_run;
        lastRunResult.textContent = data.last_result || "-";
      }

      // Cache everything for persistence across popup close/reopen
      chrome.storage.local.set({
        cachedState: state,
        cachedPhase: data.phase || null,
        cachedPhaseDetail: data.phase_detail || null,
        cachedTimeWindow: data.time_window || null,
        cachedLastRun: data.last_run || null,
      });
    })
    .catch(() => {
      // Backend unreachable — keep cached state, show hint
      console.warn("Backend unreachable, using cached state");
    });
}
