#!/usr/bin/env python3
"""
Test script to verify proxy configuration
This script will test both with and without proxy to show the difference
"""
import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from dotenv import load_dotenv
from proxy_config import setup_proxy_for_chrome, print_proxy_status, get_proxy_config

load_dotenv()

def test_ip_address(driver, test_name):
    """Test current IP address using whatismyipaddress.com"""
    print(f"\n🔍 Testing {test_name}...")
    
    try:
        driver.get("https://whatismyipaddress.com/")
        time.sleep(5)
        
        # Try to find IP address element
        try:
            ip_element = driver.find_element(By.ID, "ipv4")
            ip_address = ip_element.text
            print(f"   📍 IP Address: {ip_address}")
        except:
            try:
                # Alternative selector
                ip_element = driver.find_element(By.CSS_SELECTOR, ".ip")
                ip_address = ip_element.text
                print(f"   📍 IP Address: {ip_address}")
            except:
                print("   ❌ Could not detect IP address")
        
        # Get location info
        try:
            location_elements = driver.find_elements(By.CSS_SELECTOR, ".info-box-content")
            for elem in location_elements:
                text = elem.text.strip()
                if "Country" in text or "City" in text or "Region" in text:
                    print(f"   🌍 {text}")
        except:
            print("   ⚠️ Could not get location info")
            
    except Exception as e:
        print(f"   ❌ Error testing IP: {e}")

def test_without_proxy():
    """Test browser without proxy"""
    print("=" * 60)
    print("🔓 TESTING WITHOUT PROXY")
    print("=" * 60)
    
    options = uc.ChromeOptions()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-webrtc')
    options.set_capability('acceptInsecureCerts', True)
    
    # Don't setup proxy
    driver = uc.Chrome(options=options)
    
    try:
        test_ip_address(driver, "WITHOUT PROXY")
    finally:
        driver.quit()

def test_with_proxy():
    """Test browser with proxy"""
    print("=" * 60)
    print("🔒 TESTING WITH PROXY")
    print("=" * 60)
    
    # Check if proxy is configured
    proxy_config = get_proxy_config()
    if proxy_config is None:
        print("⚠️ Proxy not configured. Set USE_PROXY=true in .env to test with proxy.")
        return
    
    options = uc.ChromeOptions()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-webrtc')
    options.set_capability('acceptInsecureCerts', True)
    
    # Setup proxy
    options = setup_proxy_for_chrome(options)
    
    try:
        driver = uc.Chrome(options=options)
        test_ip_address(driver, "WITH PROXY")
    except Exception as e:
        print(f"❌ Error creating driver with proxy: {e}")
        return
    finally:
        try:
            driver.quit()
        except:
            pass

def main():
    """Main test function"""
    print("🧪 PROXY CONFIGURATION TEST")
    print("=" * 60)
    
    # Show current proxy configuration
    print_proxy_status()
    
    # Test without proxy first
    test_without_proxy()
    
    # Wait a bit between tests
    time.sleep(3)
    
    # Test with proxy
    test_with_proxy()
    
    print("\n" + "=" * 60)
    print("✅ PROXY TEST COMPLETED")
    print("=" * 60)
    print("\n💡 To toggle proxy usage:")
    print("   - Set USE_PROXY=true in .env to enable proxy")
    print("   - Set USE_PROXY=false in .env to disable proxy")
    print("\n🔧 If proxy test fails, check:")
    print("   - Proxy credentials in .env file")
    print("   - Internet connection")
    print("   - Proxy server availability")

if __name__ == "__main__":
    main()