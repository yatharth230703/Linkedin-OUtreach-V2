#!/usr/bin/env python3
"""
Test script to show what the orchestrator considers "user activity"
Now focuses on actual keyboard/mouse input rather than CPU or running apps
"""

import psutil
import subprocess
import sys
from pathlib import Path

def get_macos_idle_time():
    """Get system idle time on macOS"""
    try:
        result = subprocess.run(['ioreg', '-c', 'IOHIDSystem'], 
                              capture_output=True, text=True, timeout=10)
        
        for line in result.stdout.split('\n'):
            if 'HIDIdleTime' in line:
                idle_ns = int(line.split('=')[1].strip())
                return idle_ns / 1_000_000_000  # Convert to seconds
        return None
    except Exception as e:
        print(f"⚠️ Could not get macOS idle time: {e}")
        return None

def get_linux_idle_time():
    """Get system idle time on Linux"""
    try:
        result = subprocess.run(['xprintidle'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            idle_ms = int(result.stdout.strip())
            return idle_ms / 1000  # Convert to seconds
        return None
    except Exception as e:
        print(f"⚠️ Could not get Linux idle time (xprintidle): {e}")
        return None

def test_user_presence():
    """Test all user presence detection methods"""
    
    print("🔍 Testing User Presence Detection Methods (Input-Based):")
    print("=" * 60)
    
    user_active = False
    
    # Method 1: Safety file
    safety_file = Path("safety_stop.txt")
    if safety_file.exists():
        print("🛑 Method 1: Safety file EXISTS - User considered ACTIVE")
        user_active = True
    else:
        print("✅ Method 1: No safety file - OK")
    
    # Method 2: Input activity detection
    print("\n📱 Method 2: Input Activity Detection")
    
    if sys.platform == 'darwin':
        print("   Platform: macOS - Using ioreg for idle time")
        idle_time = get_macos_idle_time()
        
        if idle_time is not None:
            if idle_time < 60:
                print(f"⌨️ Recent input activity detected (idle: {idle_time:.1f}s) - User considered ACTIVE")
                user_active = True
            else:
                print(f"✅ No recent input activity (idle: {idle_time:.1f}s) - OK")
        else:
            print("⚠️ Could not determine idle time - falling back to session check")
    else:
        print("   Platform: Linux/Other - Trying xprintidle")
        idle_time = get_linux_idle_time()
        
        if idle_time is not None:
            if idle_time < 60:
                print(f"⌨️ Recent input activity detected (idle: {idle_time:.1f}s) - User considered ACTIVE")
                user_active = True
            else:
                print(f"✅ No recent input activity (idle: {idle_time:.1f}s) - OK")
        else:
            print("⚠️ xprintidle not available - falling back to session check")
    
    # Method 3: Active sessions (fallback)
    print("\n👤 Method 3: Active User Sessions (Fallback)")
    active_sessions = []
    for user in psutil.users():
        if user.terminal and user.terminal not in ['console', None]:
            active_sessions.append(f"{user.name}@{user.terminal}")
    
    if active_sessions:
        print(f"   Active sessions found: {active_sessions}")
        if idle_time is None:  # Only consider this if we couldn't get idle time
            print("   → User considered ACTIVE (fallback method)")
            user_active = True
        else:
            print("   → Sessions exist but idle time takes precedence")
    else:
        print("   ✅ No active sessions")
    
    print("\n" + "=" * 60)
    
    # Overall assessment
    if user_active:
        print("🛑 OVERALL: User is considered ACTIVE")
        print("   → Orchestrator would wait for inactivity or abort")
    else:
        print("✅ OVERALL: User is considered INACTIVE") 
        print("   → Orchestrator would proceed with bot execution")
    
    print("\n💡 Tips:")
    print("   • Move your mouse or type something to become 'active'")
    print("   • Don't touch keyboard/mouse for 60+ seconds to become 'inactive'")
    print("   • Create 'safety_stop.txt' file for manual override")
    
    return user_active

if __name__ == "__main__":
    test_user_presence()