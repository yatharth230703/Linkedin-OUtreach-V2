"""
Proxy configuration module for LinkedIn bots
Handles proxy setup for Chrome WebDriver with iProyal proxy
"""
import os
from dotenv import load_dotenv

load_dotenv()

def get_proxy_config():
    """
    Get proxy configuration from environment variables
    Returns dict with proxy settings or None if proxy is disabled
    """
    use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
    
    if not use_proxy:
        return None
    
    return {
        "host": os.getenv("PROXY_HOST"),
        "port": os.getenv("PROXY_PORT"),
        "username": os.getenv("PROXY_USERNAME"),
        "password": os.getenv("PROXY_PASSWORD")
    }

def setup_proxy_for_chrome(options, proxy_config=None):
    """
    Configure Chrome options with proxy settings
    
    Args:
        options: ChromeOptions object
        proxy_config: Dict with proxy settings (host, port, username, password)
                     If None, will get from environment
    
    Returns:
        Modified ChromeOptions object
    """
    if proxy_config is None:
        proxy_config = get_proxy_config()
    
    if proxy_config is None:
        print("🔓 Running without proxy")
        return options
    
    host = proxy_config["host"]
    port = proxy_config["port"]
    username = proxy_config["username"]
    password = proxy_config["password"]
    
    if not all([host, port, username, password]):
        print("⚠️ Incomplete proxy configuration, running without proxy")
        return options
    
    print(f"🔒 Configuring proxy: {host}:{port}")
    
    # Set proxy server
    proxy_server = f"{host}:{port}"
    options.add_argument(f"--proxy-server=http://{proxy_server}")
    
    # Create proxy auth extension
    proxy_auth_extension = create_proxy_auth_extension(
        proxy_host=host,
        proxy_port=port,
        proxy_username=username,
        proxy_password=password
    )
    
    options.add_extension(proxy_auth_extension)
    
    return options

def create_proxy_auth_extension(proxy_host, proxy_port, proxy_username, proxy_password):
    """
    Create a Chrome extension for proxy authentication
    Returns path to the extension zip file
    """
    import zipfile
    import tempfile
    
    # Create manifest.json content
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """
    
    # Create background.js content
    background_js = f"""
    var config = {{
        mode: "fixed_servers",
        rules: {{
            singleProxy: {{
                scheme: "http",
                host: "{proxy_host}",
                port: parseInt({proxy_port})
            }},
            bypassList: ["localhost"]
        }}
    }};

    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

    function callbackFn(details) {{
        return {{
            authCredentials: {{
                username: "{proxy_username}",
                password: "{proxy_password}"
            }}
        }};
    }}

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{urls: ["<all_urls>"]}},
        ['blocking']
    );
    """
    
    # Create temporary directory and zip file
    temp_dir = tempfile.mkdtemp()
    extension_path = os.path.join(temp_dir, "proxy_auth_extension.zip")
    
    with zipfile.ZipFile(extension_path, 'w') as zf:
        zf.writestr("manifest.json", manifest_json)
        zf.writestr("background.js", background_js)
    
    return extension_path

def print_proxy_status():
    """Print current proxy configuration status"""
    proxy_config = get_proxy_config()
    
    if proxy_config is None:
        print("🔓 Proxy Status: DISABLED")
        print("   To enable proxy, set USE_PROXY=true in .env file")
    else:
        print("🔒 Proxy Status: ENABLED")
        print(f"   Host: {proxy_config['host']}")
        print(f"   Port: {proxy_config['port']}")
        print(f"   Username: {proxy_config['username']}")
        print("   Password: [HIDDEN]")