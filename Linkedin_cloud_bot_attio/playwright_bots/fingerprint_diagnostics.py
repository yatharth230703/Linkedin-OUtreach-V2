"""fingerprint_diagnostics.py — DIAGNOSTIC ONLY, NO EVASION.

Captures every fingerprint signal LinkedIn (and commercial anti-bot vendors
like Arkose / DataDome / PerimeterX) are known to inspect, then writes a
detailed report to STATE_DIR/logs/fingerprint/.

Each report contains:
  - signals.json        — every JS-readable fingerprint signal
  - mismatches.json     — flagged discrepancies (e.g. timezone vs IP geo,
                          GPU vendor vs claimed UA, plugins length vs UA, etc.)
  - page.png            — full-page screenshot at capture time
  - run_meta.json       — env (headless? cloud? account?), proxy IP,
                          stealth state, Playwright/Chromium version

Call points (all bots):
  - Right after browser launch (baseline)
  - After login
  - Right before any sensitive action (Connect click, message send)
  - On any error / abort

This module changes NOTHING about the browser. It only reads.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime

# Lazy state_paths import — module is at project root
try:
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from state_paths import LOGS_DIR, slugify
    _DIAG_DIR = os.path.join(LOGS_DIR, "fingerprint")
except Exception:
    _DIAG_DIR = "/tmp/fingerprint_diag"


# ── The fingerprint-collection JS ────────────────────────────────────────
# Mirrors what bot.sannysoft.com, creepjs, and pixelscan check.
# DO NOT modify any browser state — read-only inspections.
_FINGERPRINT_JS = r"""
() => {
    const out = {};
    const safe = (fn, fallback = null) => { try { return fn(); } catch (e) { return { __error: e.message }; } };

    // ── Navigator basics ──────────────────────────────────────────
    out.navigator = {
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        languages: navigator.languages,
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: navigator.deviceMemory ?? null,
        webdriver: navigator.webdriver,
        vendor: navigator.vendor,
        maxTouchPoints: navigator.maxTouchPoints,
        cookieEnabled: navigator.cookieEnabled,
        doNotTrack: navigator.doNotTrack,
        pdfViewerEnabled: navigator.pdfViewerEnabled ?? null,
    };

    // ── Plugins / MimeTypes ──────────────────────────────────────
    out.plugins = safe(() => {
        const arr = [];
        for (let i = 0; i < navigator.plugins.length; i++) {
            arr.push({ name: navigator.plugins[i].name, filename: navigator.plugins[i].filename });
        }
        return { length: navigator.plugins.length, items: arr };
    });
    out.mimeTypes = safe(() => navigator.mimeTypes.length);

    // ── userAgentData (modern, Chromium-only) ────────────────────
    out.userAgentData = safe(() => {
        if (!navigator.userAgentData) return null;
        return {
            brands: navigator.userAgentData.brands,
            mobile: navigator.userAgentData.mobile,
            platform: navigator.userAgentData.platform,
        };
    });

    // ── Screen / window ──────────────────────────────────────────
    out.screen = {
        width: screen.width, height: screen.height,
        availWidth: screen.availWidth, availHeight: screen.availHeight,
        colorDepth: screen.colorDepth, pixelDepth: screen.pixelDepth,
        orientation: screen.orientation ? screen.orientation.type : null,
    };
    out.window = {
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
        outerWidth: window.outerWidth, outerHeight: window.outerHeight,
        devicePixelRatio: window.devicePixelRatio,
    };

    // ── Time / TZ ────────────────────────────────────────────────
    out.time = {
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        timezoneOffset: new Date().getTimezoneOffset(),
        locale: Intl.DateTimeFormat().resolvedOptions().locale,
        now: Date.now(),
    };

    // ── WebGL / GPU (huge anti-bot signal) ───────────────────────
    out.webgl = safe(() => {
        const c = document.createElement('canvas');
        const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
        if (!gl) return { unsupported: true };
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        return {
            vendor: gl.getParameter(gl.VENDOR),
            renderer: gl.getParameter(gl.RENDERER),
            unmaskedVendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
            unmaskedRenderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
            shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
            maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
            extensions: gl.getSupportedExtensions(),
        };
    });

    // ── WebGL canvas pixel hash (anti-bot vendors hash this) ─────
    out.webglPixelHash = safe(() => {
        const c = document.createElement('canvas');
        c.width = 256; c.height = 128;
        const gl = c.getContext('webgl');
        if (!gl) return null;
        gl.clearColor(0.2, 0.4, 0.6, 1.0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        // Read back pixels
        const pixels = new Uint8Array(4 * 4 * 4);
        gl.readPixels(0, 0, 4, 4, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        return Array.from(pixels);
    });

    // ── Canvas 2D fingerprint ────────────────────────────────────
    out.canvas2dHash = safe(() => {
        const c = document.createElement('canvas');
        c.width = 200; c.height = 50;
        const ctx = c.getContext('2d');
        ctx.textBaseline = 'top';
        ctx.font = "14px 'Arial'";
        ctx.fillStyle = '#f60';
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = '#069';
        ctx.fillText('fingerprint', 2, 15);
        // Hash via dataURL (substring to keep size small)
        const url = c.toDataURL();
        let h = 0;
        for (let i = 0; i < url.length; i++) h = ((h << 5) - h + url.charCodeAt(i)) | 0;
        return { hash: h, length: url.length, sample: url.substring(0, 100) };
    });

    // ── Audio fingerprint ───────────────────────────────────────
    out.audioFingerprint = safe(() => {
        const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        if (!Ctx) return { unsupported: true };
        const ctx = new Ctx(1, 44100, 44100);
        return {
            sampleRate: ctx.sampleRate,
            destinationMaxChannelCount: ctx.destination.maxChannelCount,
        };
    });

    // ── CDP / Automation detection vectors ───────────────────────
    out.automation = {
        webdriver: navigator.webdriver,
        chrome: !!window.chrome,
        chromeRuntime: !!(window.chrome && window.chrome.runtime),
        chromeApp: !!(window.chrome && window.chrome.app),
        // Common CDP-injected globals
        cdc_keys: Object.keys(window).filter(k => k.startsWith('cdc_')),
        playwright_keys: Object.keys(window).filter(k =>
            k.includes('playwright') || k.includes('__pw') || k.includes('__PW')),
        puppeteer_keys: Object.keys(window).filter(k => k.includes('puppeteer')),
        // Permissions API quirk: bots return 'default' for notifications even when denied
        notificationPermission: Notification ? Notification.permission : null,
    };

    // ── Permissions API (notification quirk is a known bot tell) ─
    out.permissions = safe(() => {
        return new Promise(resolve => {
            navigator.permissions.query({ name: 'notifications' })
                .then(p => resolve({ name: 'notifications', state: p.state }))
                .catch(e => resolve({ error: e.message }));
        });
    });

    // ── Battery API (cloud has none) ────────────────────────────
    out.battery = safe(() => {
        if (!navigator.getBattery) return { unsupported: true };
        return navigator.getBattery().then(b => ({
            charging: b.charging, level: b.level,
        })).catch(e => ({ error: e.message }));
    });

    // ── Network connection ──────────────────────────────────────
    out.connection = safe(() => {
        if (!navigator.connection) return null;
        return {
            effectiveType: navigator.connection.effectiveType,
            rtt: navigator.connection.rtt,
            downlink: navigator.connection.downlink,
            saveData: navigator.connection.saveData,
        };
    });

    // ── Media devices count (cloud has 0) ───────────────────────
    out.mediaDevices = safe(() => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return null;
        return navigator.mediaDevices.enumerateDevices().then(devs => ({
            audioInput: devs.filter(d => d.kind === 'audioinput').length,
            audioOutput: devs.filter(d => d.kind === 'audiooutput').length,
            videoInput: devs.filter(d => d.kind === 'videoinput').length,
        })).catch(e => ({ error: e.message }));
    });

    // ── Fonts (sample of installed fonts via measurement) ───────
    out.fontProbe = safe(() => {
        const probes = ['Arial', 'Times New Roman', 'Courier New', 'Comic Sans MS',
                        'Tahoma', 'Verdana', 'Georgia', 'Impact', 'Trebuchet MS',
                        'Lucida Console', 'Microsoft YaHei', 'Hiragino Sans'];
        const baseFonts = ['monospace', 'serif', 'sans-serif'];
        const span = document.createElement('span');
        span.style.cssText = 'position:absolute;left:-9999px;font-size:72px';
        span.textContent = 'mmmmmmmmmmlli';
        document.body.appendChild(span);
        const baseSizes = {};
        for (const b of baseFonts) {
            span.style.fontFamily = b;
            baseSizes[b] = { w: span.offsetWidth, h: span.offsetHeight };
        }
        const detected = [];
        for (const f of probes) {
            for (const b of baseFonts) {
                span.style.fontFamily = `'${f}',${b}`;
                if (span.offsetWidth !== baseSizes[b].w || span.offsetHeight !== baseSizes[b].h) {
                    detected.push(f);
                    break;
                }
            }
        }
        document.body.removeChild(span);
        return detected;
    });

    return out;
}
"""


def _detect_mismatches(signals, run_meta):
    """Compare collected signals against expected values; flag discrepancies.

    Each mismatch is a strong signal LinkedIn could use to identify us as a bot.
    """
    flags = []

    nav = signals.get("navigator", {}) or {}
    ua = nav.get("userAgent", "") or ""

    # 1. webdriver flag still set despite stealth
    if nav.get("webdriver") is True:
        flags.append({"severity": "CRITICAL", "field": "navigator.webdriver",
                      "value": True, "reason": "Stealth failed to hide webdriver flag"})

    # 2. UA claims Windows but platform says Linux/Mac
    if "Windows" in ua and not (nav.get("platform", "").startswith("Win")):
        flags.append({"severity": "HIGH", "field": "platform_vs_ua",
                      "ua": ua[:60], "platform": nav.get("platform"),
                      "reason": "User-Agent claims Windows but navigator.platform disagrees"})

    # 3. Plugins length 0 (real Chrome has at least PDF viewer)
    plugins = signals.get("plugins") or {}
    if isinstance(plugins, dict) and plugins.get("length", 0) == 0:
        flags.append({"severity": "MEDIUM", "field": "plugins.length", "value": 0,
                      "reason": "Real Chrome ships with at least 1 PDF viewer plugin"})

    # 4. Languages mismatch
    langs = nav.get("languages") or []
    if not langs or (isinstance(langs, list) and len(langs) == 0):
        flags.append({"severity": "MEDIUM", "field": "navigator.languages",
                      "value": langs, "reason": "Empty languages array is a known bot tell"})

    # 5. Timezone mismatch with proxy IP
    tz = (signals.get("time") or {}).get("timezone")
    proxy_geo = run_meta.get("proxy_geo")
    if tz and proxy_geo:
        # Crude check: if proxy is India, expect Asia/* tz
        if proxy_geo == "IN" and not (tz or "").startswith("Asia/"):
            flags.append({"severity": "HIGH", "field": "timezone_vs_geo",
                          "tz": tz, "geo": proxy_geo,
                          "reason": "Browser timezone doesn't match proxy IP country"})
        if proxy_geo == "DE" and not (tz or "").startswith("Europe/"):
            flags.append({"severity": "HIGH", "field": "timezone_vs_geo",
                          "tz": tz, "geo": proxy_geo,
                          "reason": "Browser timezone doesn't match proxy IP country"})

    # 6. WebGL renderer says SwiftShader → headless/cloud signal
    webgl = signals.get("webgl") or {}
    if isinstance(webgl, dict):
        rend = (webgl.get("renderer") or "") + " " + (webgl.get("unmaskedRenderer") or "")
        for tell in ("SwiftShader", "Mesa", "llvmpipe", "Software"):
            if tell.lower() in rend.lower():
                flags.append({"severity": "CRITICAL", "field": "webgl.renderer",
                              "value": rend.strip(),
                              "reason": f"GPU renderer contains '{tell}' — clear cloud/headless signal"})
                break

    # 7. CDP-injected globals
    auto = signals.get("automation") or {}
    if auto.get("cdc_keys"):
        flags.append({"severity": "CRITICAL", "field": "window.cdc_*",
                      "value": auto["cdc_keys"][:5],
                      "reason": "ChromeDriver CDP variables present in window"})
    if auto.get("playwright_keys"):
        flags.append({"severity": "CRITICAL", "field": "window.__pw*",
                      "value": auto["playwright_keys"][:5],
                      "reason": "Playwright init globals leaked into page context"})

    # 8. outerHeight === 0 (headless tell)
    win = signals.get("window") or {}
    if win.get("outerHeight") == 0 or win.get("outerWidth") == 0:
        flags.append({"severity": "HIGH", "field": "window.outerSize", "value": win,
                      "reason": "outer dimensions of 0 indicate headless without proper window"})

    # 9. hardwareConcurrency unusual
    hc = nav.get("hardwareConcurrency")
    if hc is not None and (hc < 2 or hc > 32):
        flags.append({"severity": "LOW", "field": "navigator.hardwareConcurrency",
                      "value": hc, "reason": "Unusual CPU core count"})

    # 10. No media devices — cloud VM tell
    md = signals.get("mediaDevices") or {}
    if isinstance(md, dict) and md.get("audioInput") == 0 and md.get("videoInput") == 0 and md.get("audioOutput") == 0:
        flags.append({"severity": "HIGH", "field": "mediaDevices",
                      "value": md, "reason": "Zero audio+video devices — cloud VM signature"})

    # 11. Battery API unsupported (laptops/phones have it)
    batt = signals.get("battery") or {}
    if isinstance(batt, dict) and batt.get("unsupported"):
        flags.append({"severity": "LOW", "field": "battery",
                      "reason": "Battery API unsupported (most real desktops/laptops have it)"})

    # 12. Notification.permission == 'default' even after grant attempts
    perms = signals.get("permissions") or {}
    if isinstance(perms, dict) and perms.get("state") == "default":
        flags.append({"severity": "MEDIUM", "field": "notification.permission",
                      "reason": "Notification permission == 'default' is a known headless tell"})

    # 13. Connection.rtt always 50 (Chromium quirk)
    conn = signals.get("connection") or {}
    if isinstance(conn, dict) and conn.get("rtt") == 50:
        flags.append({"severity": "LOW", "field": "connection.rtt",
                      "value": 50, "reason": "rtt=50 is the Chromium default in headless"})

    # 14. UserAgentData mobile flag mismatch
    uad = signals.get("userAgentData") or {}
    if isinstance(uad, dict) and uad.get("brands"):
        # Check for HeadlessChrome brand
        brand_str = json.dumps(uad.get("brands", []))
        if "Headless" in brand_str:
            flags.append({"severity": "CRITICAL", "field": "userAgentData.brands",
                          "value": uad["brands"], "reason": "HeadlessChrome listed in brand string"})

    # 15. Fonts list too short (real desktops have 100+)
    fonts = signals.get("fontProbe") or []
    if isinstance(fonts, list) and len(fonts) < 5:
        flags.append({"severity": "MEDIUM", "field": "fonts",
                      "value": fonts, "reason": f"Only {len(fonts)} common fonts detected — cloud VM signature"})

    return flags


def capture(page, account_name="", checkpoint="generic", proxy_geo=None, screenshot=True):
    """Capture a full diagnostic snapshot.

    Args:
        page: Playwright Page
        account_name: For per-account diagnostic dirs
        checkpoint: Label for this capture point (e.g. 'post_login', 'pre_connect_click')
        proxy_geo: 2-letter country code of proxy ('IN', 'DE') for mismatch checks
        screenshot: If True, also save a viewport screenshot

    Writes to:
        STATE_DIR/logs/fingerprint/<ts>_<account>_<checkpoint>.{json,png}
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(account_name) if account_name else "unknown"
    base = os.path.join(_DIAG_DIR, f"{ts}_{slug}_{checkpoint}")

    try:
        os.makedirs(_DIAG_DIR, exist_ok=True)
    except Exception:
        pass

    # ── Run-level metadata ─────────────────────────────────────────
    run_meta = {
        "timestamp": ts,
        "account": account_name,
        "checkpoint": checkpoint,
        "proxy_geo": proxy_geo,
        "env": {
            "CLOUD_MODE": os.getenv("CLOUD_MODE"),
            "DISPLAY": os.getenv("DISPLAY"),
            "DISABLE_STEALTH": os.getenv("DISABLE_STEALTH"),
            "SKIP_COOKIE_LOGIN": os.getenv("SKIP_COOKIE_LOGIN"),
            "USE_PROXY": os.getenv("USE_PROXY"),
        },
        "page_url": None,
        "page_title": None,
    }
    try:
        run_meta["page_url"] = page.url
        run_meta["page_title"] = page.title()
    except Exception as e:
        run_meta["page_state_error"] = str(e)

    # ── JS-side fingerprint collection ────────────────────────────
    signals = {}
    try:
        # Async JS — Playwright awaits the returned Promise
        signals = page.evaluate(_FINGERPRINT_JS)
    except Exception as e:
        signals = {"__capture_error": str(e), "__traceback": traceback.format_exc()[:500]}

    # Resolve any nested Promises (Playwright auto-resolves top-level, but
    # nested ones in our return object may still be Promise references)
    for k in ("permissions", "battery", "mediaDevices"):
        v = signals.get(k)
        if isinstance(v, dict) and "__error" in v:
            signals[k] = v
        elif v is not None and not isinstance(v, (dict, list, int, str, float, bool)):
            # Promise that didn't resolve — try a separate eval
            try:
                if k == "permissions":
                    signals[k] = page.evaluate(
                        "() => navigator.permissions.query({name:'notifications'}).then(p => ({state: p.state}))"
                    )
                elif k == "battery":
                    signals[k] = page.evaluate(
                        "() => navigator.getBattery ? navigator.getBattery().then(b => ({charging: b.charging, level: b.level})) : {unsupported: true}"
                    )
                elif k == "mediaDevices":
                    signals[k] = page.evaluate(
                        "() => navigator.mediaDevices.enumerateDevices().then(devs => ({"
                        "audioInput: devs.filter(d=>d.kind==='audioinput').length,"
                        "audioOutput: devs.filter(d=>d.kind==='audiooutput').length,"
                        "videoInput: devs.filter(d=>d.kind==='videoinput').length}))"
                    )
            except Exception as e:
                signals[k] = {"__error": str(e)}

    # ── Detect mismatches ─────────────────────────────────────────
    mismatches = _detect_mismatches(signals, run_meta)

    # ── Write everything ──────────────────────────────────────────
    try:
        with open(base + "_signals.json", "w") as f:
            json.dump(signals, f, indent=2, default=str)
        with open(base + "_meta.json", "w") as f:
            json.dump(run_meta, f, indent=2, default=str)
        with open(base + "_mismatches.json", "w") as f:
            json.dump(mismatches, f, indent=2, default=str)
    except Exception as e:
        print(f"   [diag] write failed: {e}")

    # ── Screenshot ────────────────────────────────────────────────
    if screenshot:
        try:
            page.screenshot(path=base + ".png", full_page=False)
        except Exception as e:
            print(f"   [diag] screenshot failed: {e}")

    # ── Console summary ───────────────────────────────────────────
    crit = [m for m in mismatches if m.get("severity") == "CRITICAL"]
    high = [m for m in mismatches if m.get("severity") == "HIGH"]
    med = [m for m in mismatches if m.get("severity") == "MEDIUM"]
    low = [m for m in mismatches if m.get("severity") == "LOW"]
    print(f"   [diag:{checkpoint}] CRIT={len(crit)} HIGH={len(high)} MED={len(med)} LOW={len(low)} → {base}")
    for m in crit + high:
        print(f"      🚩 {m.get('severity')} {m.get('field')}: {m.get('reason')}")

    return {"path": base, "mismatches": mismatches, "signals": signals}


def safe_capture(page, account_name="", checkpoint="generic", proxy_geo=None, screenshot=True):
    """Wrapper that never raises — diagnostics must not break the bot."""
    try:
        return capture(page, account_name=account_name, checkpoint=checkpoint,
                       proxy_geo=proxy_geo, screenshot=screenshot)
    except Exception as e:
        print(f"   [diag] safe_capture failed silently: {e}")
        return None
