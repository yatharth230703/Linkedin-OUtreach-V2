#!/usr/bin/env python3
"""
Simple script to toggle proxy on/off in .env file
"""
import os
import sys

def read_env_file():
    """Read .env file and return lines"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    
    if not os.path.exists(env_path):
        print(f"❌ .env file not found at {env_path}")
        return None, None
    
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    return lines, env_path

def write_env_file(lines, env_path):
    """Write lines back to .env file"""
    with open(env_path, 'w') as f:
        f.writelines(lines)

def get_current_proxy_status(lines):
    """Get current proxy status from .env lines"""
    for line in lines:
        if line.strip().startswith('USE_PROXY'):
            if '=' in line:
                value = line.split('=', 1)[1].strip().strip('"').lower()
                return value == 'true'
    return False

def toggle_proxy_status(lines):
    """Toggle proxy status in .env lines"""
    current_status = get_current_proxy_status(lines)
    new_status = not current_status
    new_value = "true" if new_status else "false"
    
    # Find and update USE_PROXY line
    for i, line in enumerate(lines):
        if line.strip().startswith('USE_PROXY'):
            lines[i] = f'USE_PROXY = "{new_value}"\n'
            break
    else:
        # If USE_PROXY line doesn't exist, add it
        lines.append(f'USE_PROXY = "{new_value}"\n')
    
    return new_status

def main():
    """Main function"""
    print("🔄 PROXY TOGGLE UTILITY")
    print("=" * 40)
    
    # Read .env file
    lines, env_path = read_env_file()
    if lines is None:
        return
    
    # Get current status
    current_status = get_current_proxy_status(lines)
    print(f"📊 Current proxy status: {'ENABLED' if current_status else 'DISABLED'}")
    
    # Check if user wants to toggle
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action in ['on', 'enable', 'true']:
            target_status = True
        elif action in ['off', 'disable', 'false']:
            target_status = False
        elif action in ['toggle', 'switch']:
            target_status = not current_status
        else:
            print(f"❌ Unknown action: {action}")
            print("💡 Usage: python toggle_proxy.py [on|off|toggle]")
            return
    else:
        # Interactive mode
        action = input(f"\n🤔 Do you want to {'disable' if current_status else 'enable'} proxy? (y/n): ").lower()
        if action not in ['y', 'yes']:
            print("❌ Operation cancelled")
            return
        target_status = not current_status
    
    # Update if needed
    if target_status == current_status:
        print(f"✅ Proxy is already {'ENABLED' if current_status else 'DISABLED'}")
        return
    
    # Toggle status
    new_status = toggle_proxy_status(lines)
    
    # Write back to file
    write_env_file(lines, env_path)
    
    print(f"✅ Proxy status changed to: {'ENABLED' if new_status else 'DISABLED'}")
    print(f"📁 Updated: {env_path}")
    
    if new_status:
        print("\n🔒 Proxy is now ENABLED")
        print("   All bots will use the iProyal proxy")
    else:
        print("\n🔓 Proxy is now DISABLED") 
        print("   All bots will use direct connection")
    
    print("\n💡 You can also run:")
    print("   python toggle_proxy.py on     # Enable proxy")
    print("   python toggle_proxy.py off    # Disable proxy")
    print("   python toggle_proxy.py toggle # Toggle current state")

if __name__ == "__main__":
    main()