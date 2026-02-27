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

const dailyConnect = document.getElementById("daily-connect");
const dailyMessage = document.getElementById("daily-message");
const dailyFollowup = document.getElementById("daily-followup");
const accountName = document.getElementById("account-name");
const backendUrl = document.getElementById("backend-url");

// Template elements
const templateSelect = document.getElementById("template-select");
const templateFile = document.getElementById("template-file");
const uploadTemplateBtn = document.getElementById("upload-template-btn");
const templatePreview = document.getElementById("template-preview");
const previewContent = document.getElementById("preview-content");

// State
let botRunning = false;

// Init
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get(["loggedIn", "botRunning", "accountName", "backendUrl"], (data) => {
    if (data.backendUrl) {
      BACKEND_URL = data.backendUrl;
      backendUrl.value = data.backendUrl;
    } else {
      backendUrl.value = BACKEND_URL;
    }
    if (data.accountName) {
      accountName.value = data.accountName;
    }
    if (data.loggedIn) {
      showMainScreen();
      if (data.botRunning) {
        setBotRunning(true);
      }
      fetchStatus();
      loadTemplates();
    }
  });
});

// Backend URL change handler
backendUrl.addEventListener("change", () => {
  let url = backendUrl.value.trim();
  // Remove trailing slash
  if (url.endsWith("/")) url = url.slice(0, -1);
  BACKEND_URL = url;
  backendUrl.value = url;
  chrome.storage.local.set({ backendUrl: url });
});

// Persist account name on change
accountName.addEventListener("change", () => {
  chrome.storage.local.set({ accountName: accountName.value.trim() });
});

// Login
loginBtn.addEventListener("click", () => {
  const user = document.getElementById("username").value.trim();
  const pass = document.getElementById("password").value.trim();

  if (user === BETA_USERNAME && pass === BETA_PASSWORD) {
    chrome.storage.local.set({ loggedIn: true });
    loginError.classList.add("hidden");
    showMainScreen();
    loadTemplates();
  } else {
    loginError.classList.remove("hidden");
  }
});

// Logout
logoutBtn.addEventListener("click", () => {
  chrome.storage.local.set({ loggedIn: false, botRunning: false });
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
      // Find any LinkedIn tab (not just active - popup might steal focus)
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

  // Send config then start
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
        setBotRunning(true);
        chrome.storage.local.set({ botRunning: true });
      } else {
        alert("Failed to start: " + (data.error || "Unknown error"));
      }
    })
    .catch((err) => {
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
        setBotRunning(false);
        chrome.storage.local.set({ botRunning: false });
      }
    })
    .catch((err) => {
      alert("Connection failed.");
    })
    .finally(() => {
      stopBtn.disabled = false;
      stopBtn.textContent = "Stop Bot";
    });
});

// ── Template Management ──────────────────────────────────────────────────

function loadTemplates() {
  fetch(`${BACKEND_URL}/api/templates`, {
    headers: { "X-Api-Key": API_KEY },
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.success && data.templates) {
        templateSelect.innerHTML = "";
        if (data.templates.length === 0) {
          templateSelect.innerHTML = '<option value="">No templates found</option>';
          return;
        }
        data.templates.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t.filename;
          opt.textContent = `${t.filename} - ${t.description.substring(0, 40)}...`;
          templateSelect.appendChild(opt);
        });
      }
    })
    .catch(() => {
      templateSelect.innerHTML = '<option value="">Backend unreachable</option>';
    });
}

// Upload template button triggers file picker
uploadTemplateBtn.addEventListener("click", () => {
  templateFile.click();
});

// Handle file selection
templateFile.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  try {
    const text = await file.text();
    const templateData = JSON.parse(text);

    // Client-side validation
    const required = ["outreach_prompt", "followup_1_prompt", "followup_2_prompt",
                      "followup_3_prompt", "followup_4_prompt"];
    const missing = required.filter((k) => !templateData[k]);
    if (missing.length > 0) {
      alert(`Invalid template. Missing keys: ${missing.join(", ")}`);
      templateFile.value = "";
      return;
    }

    uploadTemplateBtn.disabled = true;
    uploadTemplateBtn.textContent = "Uploading...";

    // Upload to backend
    const res = await fetch(`${BACKEND_URL}/api/templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
      body: JSON.stringify(templateData),
    });
    const result = await res.json();

    if (result.success) {
      // Show preview
      uploadTemplateBtn.textContent = "Generating preview...";
      const previewRes = await fetch(`${BACKEND_URL}/api/templates/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Api-Key": API_KEY },
        body: JSON.stringify(templateData),
      });
      const previewData = await previewRes.json();

      if (previewData.success) {
        showPreview(previewData.messages);
      }

      loadTemplates();
      alert(`Template saved as ${result.filename}`);
    } else {
      alert("Upload failed: " + (result.error || "Unknown error"));
    }
  } catch (err) {
    if (err instanceof SyntaxError) {
      alert("Invalid JSON file. Please check the template format.");
    } else {
      alert("Upload error: " + err.message);
    }
  } finally {
    uploadTemplateBtn.disabled = false;
    uploadTemplateBtn.textContent = "Upload New Template";
    templateFile.value = "";
  }
});

function showPreview(messages) {
  if (!messages) return;

  const labels = {
    outreach: "Connection Request",
    followup_1: "Follow-up 1",
    followup_2: "Follow-up 2",
    followup_3: "Follow-up 3",
    followup_4: "Follow-up 4",
  };

  let html = "";
  for (const [key, label] of Object.entries(labels)) {
    const msg = messages[key] || "(not generated)";
    html += `<div class="preview-message">
      <strong>${label}:</strong>
      <p>${msg.replace(/\n/g, "<br>")}</p>
    </div>`;
  }

  previewContent.innerHTML = html;
  templatePreview.classList.remove("hidden");
}

// ── Helpers ──────────────────────────────────────────────────────────────

function showMainScreen() {
  loginScreen.classList.add("hidden");
  mainScreen.classList.remove("hidden");
}

function setBotRunning(running) {
  botRunning = running;
  if (running) {
    statusBar.className = "status-bar status-running";
    statusText.textContent = "Running (daily automation active)";
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
      if (data.running !== undefined) {
        setBotRunning(data.running);
        chrome.storage.local.set({ botRunning: data.running });
      }
      if (data.last_run) {
        lastRunInfo.classList.remove("hidden");
        lastRunTime.textContent = data.last_run;
        lastRunResult.textContent = data.last_result || "-";
      }
    })
    .catch(() => {
      // Backend unreachable, keep local state
    });
}
