import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

def test_permutation(name, user, password, host, port):
    print(f"\n🧪 Testing Permutation: {name}")
    print(f"   User: {user}")
    print(f"   Pass: {password}")
    
    # Construct proxy URL
    # IMPORTANT: requests needs the scheme in the proxy URL
    proxy_url = f"http://{user}:{password}@{host}:{port}"
    proxies = {
        "http": proxy_url,
        "https": proxy_url, 
    }
    
    try:
        # We use http protocol to avoid SSL cert issues initially, though https is better for security
        target_url = "http://httpbin.org/ip"
        
        print(f"   ⏳ Sending request to {target_url}...")
        resp = requests.get(target_url, proxies=proxies, timeout=10)
        
        if resp.status_code == 200:
            print(f"   ✅ SUCCESS! Connection Established.")
            print(f"   🌍 Proxy IP: {resp.json().get('origin')}")
            return True
        elif resp.status_code == 407:
            print(f"   ❌ Auth Failed (407). Proxy rejected credentials.")
            # Print headers/body to see if there's a reason
            print(f"   📩 Server Message: {resp.text.strip()[:100]}") # First 100 chars
            print(f"   📨 Auth Header: {resp.headers.get('Proxy-Authenticate')}")
            return False
        else:
            print(f"   ❌ Failed. Status: {resp.status_code}")
            return False
            
    except requests.exceptions.ProxyError as e:
        print(f"   ❌ Proxy Error (Hard Fail): {e}")
        # Identify if it's a connection refused or auth error wrapped
        if "407" in str(e):
             print(f"      -> Confirmed 407 Proxy Auth Required")
        return False
    except Exception as e:
        print(f"   ❌ Connection Error: {e}")
        return False

def main():
    host = os.getenv("PROXY_HOST")
    port = os.getenv("PROXY_PORT")
    env_user = os.getenv("PROXY_USERNAME", "")
    env_pass = os.getenv("PROXY_PASSWORD", "")
    
    if not all([host, port, env_user, env_pass]):
        print("⚠️ Missing environment variables. Please check .env file.")
        return

    print(f"🔍 Diagnosing IPRoyal Connection for {host}:{port}")
    
    results = []
    
    # PERMUTATION 1: Env Vars As-Is (Most likely intended)
    results.append(test_permutation("1. Direct from .env", env_user, env_pass, host, port))
    
    # PERMUTATION 2: Country Flag Swap
    # IPRoyal often uses 'user_country-cc' syntax.
    # Check if '_country-' is in password
    if "_country-" in env_pass:
        parts = env_pass.split("_country-")
        clean_pass = parts[0]
        country_part = "_country-" + parts[1]
        
        new_user = env_user + country_part
        results.append(test_permutation("2. Moving country flag to Username", new_user, clean_pass, host, port))
        
    # Check if all failed
    all_failed_407 = all(result is False for result in results)
        
    # PERMUTATION 3: Session ID injection (common for sticky sessions)
    # Sometimes just appending a random session ID helps if sessions are locked
    import random
    import string
    session_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    new_user_sess = f"{env_user}_session-{session_id}"
    # test_permutation("3. With Random Session ID", new_user_sess, env_pass, host, port)

    print("\n💡 DIAGNOSIS:")
    
    # Get Local IP for user reference
    try:
        local_ip = requests.get("https://api.ipify.org", proxies={"http": None, "https": None}, timeout=5).text
        print(f"👉 Your Local IP is: {local_ip}")
        print(f"   PLEASE WHITELIST THIS IP IN YOUR IPROYAL DASHBOARD if required.")
    except:
        print("👉 Could not deterimine local IP. Please check whatismyip.com")

    if all_failed_407:
        print("\n❌ CRITICAL: ALL TESTS FAILED WITH 407 (AUTH REQUIRED)")
        print("1. Your username/password is incorrect.")
        print("2. Your Data Usage limit might be reached (expired plan).")
        print(f"3. Your IP address ({local_ip}) needs to be whitelisted.")
        print("4. You selected 'SOCKS5' in dashboard but are using HTTP port.")
    else:
        print("\n⚠️ Some tests failed, but others might have succeeded.")

if __name__ == "__main__":
    main()
