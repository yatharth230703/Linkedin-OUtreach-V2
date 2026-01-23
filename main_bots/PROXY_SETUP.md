# Proxy Setup Guide

This guide explains how to use the proxy configuration with your LinkedIn bots.

## Overview

The proxy setup allows you to route your bot traffic through an iProyal proxy server. This can help with:
- IP rotation and anonymization
- Geographic location spoofing
- Avoiding rate limits
- Testing from different locations

## Configuration

### 1. Environment Variables

The proxy configuration is stored in your `.env` file:

```env
# Proxy Configuration (iProyal)
USE_PROXY = "false"
PROXY_HOST = "geo.iproyal.com"
PROXY_PORT = "12321"
PROXY_USERNAME = "YvweObwSeViH9PEu"
PROXY_PASSWORD = "aFCTd3w0bSimAqEp_country-de"
```

### 2. Toggle Proxy On/Off

You can easily enable or disable the proxy using the toggle script:

```bash
# Interactive mode
python toggle_proxy.py

# Command line mode
python toggle_proxy.py on      # Enable proxy
python toggle_proxy.py off     # Disable proxy
python toggle_proxy.py toggle  # Toggle current state
```

## Testing

### Test Proxy Configuration

Run the test script to verify your proxy setup:

```bash
python test_proxy.py
```

This will:
1. Test your connection without proxy (show your real IP)
2. Test your connection with proxy (show proxy IP)
3. Display location information for both

### Expected Output

**Without Proxy:**
```
🔓 TESTING WITHOUT PROXY
📍 IP Address: [Your Real IP]
🌍 Country: [Your Real Country]
```

**With Proxy:**
```
🔒 TESTING WITH PROXY
📍 IP Address: [Proxy IP]
🌍 Country: Germany (or configured country)
```

## Bot Integration

All three main bots now support proxy configuration:

1. **msg_draft_connection_bot1.py** - Profile scraping and connection requests
2. **send_message.py** - First message sending
3. **send_followup.py** - Follow-up message sending

### Proxy Status Display

When you run any bot, it will show the current proxy status:

```
🔒 Proxy Status: ENABLED
   Host: geo.iproyal.com
   Port: 12321
   Username: YvweObwSeViH9PEu
   Password: [HIDDEN]
```

or

```
🔓 Proxy Status: DISABLED
   To enable proxy, set USE_PROXY=true in .env file
```

## Troubleshooting

### Common Issues

1. **Proxy Authentication Failed**
   - Check username/password in .env file
   - Verify proxy credentials with iProyal

2. **Connection Timeout**
   - Check internet connection
   - Verify proxy server is accessible
   - Try disabling proxy temporarily

3. **Chrome Extension Error**
   - The proxy uses a Chrome extension for authentication
   - If you see extension-related errors, try running without proxy first

### Debug Steps

1. **Test without proxy first:**
   ```bash
   python toggle_proxy.py off
   python test_proxy.py
   ```

2. **Test with proxy:**
   ```bash
   python toggle_proxy.py on
   python test_proxy.py
   ```

3. **Check proxy credentials:**
   - Verify in iProyal dashboard
   - Ensure account has sufficient credits
   - Check if IP is whitelisted (if required)

## Security Notes

- Proxy credentials are stored in `.env` file - keep this secure
- The password contains special characters - ensure proper escaping
- Chrome extension is created temporarily and cleaned up automatically

## Files

- `proxy_config.py` - Main proxy configuration module
- `toggle_proxy.py` - Utility to enable/disable proxy
- `test_proxy.py` - Test script to verify proxy setup
- `PROXY_SETUP.md` - This documentation file

## Usage Examples

### Enable proxy for testing
```bash
python toggle_proxy.py on
python msg_draft_connection_bot1.py
```

### Disable proxy for normal operation
```bash
python toggle_proxy.py off
python send_message.py
```

### Quick proxy test
```bash
python test_proxy.py
```