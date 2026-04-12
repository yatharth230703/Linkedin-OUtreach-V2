"""Diagnose iproyal proxy state without touching the dashboard.

Tests, in order:
  1. Direct (no proxy) — what's our real IP?
  2. Proxy w/ raw PROXY_PASSWORD — does the account auth at all?
  3. Proxy w/ BASE + geo (no sticky) — does India/Delhi geo work, rotating exits?
  4. Proxy w/ BASE + geo + FRESH sticky session — does new sticky work?
  5. Same fresh sticky → linkedin.com homepage
  6. Same fresh sticky → the profile URL that died in the run
  7. SECOND fresh sticky → same profile URL (rule out per-IP block)

Each test prints: pass/fail, status code, exit IP if available, error tail.
Secrets never echoed.
"""
import secrets
import sys
import time
from dotenv import dotenv_values
import requests

env = dotenv_values(".env")
HOST = env["PROXY_HOST"]
PORT = env["PROXY_PORT"]
USER = env["PROXY_USERNAME"]
RAW_PASS = env["PROXY_PASSWORD"]
BASE = env["PROXY_PASSWORD_BASE"]
GEO = "_country-in_city-delhi"

IPINFO = "https://api.ipify.org?format=json"
LINKEDIN_HOME = "https://www.linkedin.com/"
PROFILE_URL = "https://www.linkedin.com/in/vanshdhawan60/"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def proxies(password):
    url = f"http://{USER}:{password}@{HOST}:{PORT}"
    return {"http": url, "https": url}


def run(label, password, target, expect_json_ip=False, timeout=20):
    print(f"\n── {label}")
    try:
        t0 = time.time()
        r = requests.get(
            target,
            proxies=proxies(password) if password is not None else None,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=False,
        )
        dt = time.time() - t0
        print(f"   status={r.status_code}  bytes={len(r.content)}  time={dt:.1f}s")
        if "location" in (k.lower() for k in r.headers):
            loc = next(v for k, v in r.headers.items() if k.lower() == "location")
            print(f"   redirect→ {loc[:120]}")
        if expect_json_ip:
            try:
                print(f"   exit IP = {r.json().get('ip')}")
            except Exception:
                print(f"   body[:200] = {r.text[:200]!r}")
        return True
    except requests.exceptions.ProxyError as e:
        print(f"   PROXY ERROR: {str(e)[-200:]}")
    except requests.exceptions.ConnectTimeout as e:
        print(f"   CONNECT TIMEOUT: {str(e)[-200:]}")
    except requests.exceptions.ReadTimeout as e:
        print(f"   READ TIMEOUT: {str(e)[-200:]}")
    except Exception as e:
        print(f"   {type(e).__name__}: {str(e)[-200:]}")
    return False


print("=" * 60)
print(" Proxy Diagnostic")
print(f" host={HOST}:{PORT}  user={USER[:6]}…  base_len={len(BASE)}")
print("=" * 60)

# 1. Real IP
run("1. DIRECT (no proxy) → ipify", None, IPINFO, expect_json_ip=True)

# 2. Raw PROXY_PASSWORD (whatever shape it's stored in)
run("2. RAW PROXY_PASSWORD → ipify", RAW_PASS, IPINFO, expect_json_ip=True)

# 3. BASE + geo, no sticky → rotates exits per connection
run("3. BASE+geo (no sticky) → ipify", BASE + GEO, IPINFO, expect_json_ip=True)
run("3b. BASE+geo (no sticky) → ipify (2nd call, should be different IP)",
    BASE + GEO, IPINFO, expect_json_ip=True)

# 4. Fresh sticky session
sess1 = secrets.token_hex(8)
pw1 = f"{BASE}{GEO}_session-{sess1}"
print(f"\n   [sticky session #1: {sess1[:8]}…]")
run("4. BASE+geo+sticky#1 → ipify", pw1, IPINFO, expect_json_ip=True)
run("4b. sticky#1 → ipify (2nd call, should be SAME IP if sticky works)",
    pw1, IPINFO, expect_json_ip=True)

# 5. sticky#1 → linkedin homepage
run("5. sticky#1 → linkedin.com/", pw1, LINKEDIN_HOME)

# 6. sticky#1 → failing profile
run("6. sticky#1 → /in/vanshdhawan60/", pw1, PROFILE_URL)

# 7. Fresh sticky, hit profile directly
sess2 = secrets.token_hex(8)
pw2 = f"{BASE}{GEO}_session-{sess2}"
print(f"\n   [sticky session #2: {sess2[:8]}…]")
run("7a. sticky#2 → ipify", pw2, IPINFO, expect_json_ip=True)
run("7b. sticky#2 → /in/vanshdhawan60/", pw2, PROFILE_URL)

print("\n" + "=" * 60)
print(" done")
print("=" * 60)
