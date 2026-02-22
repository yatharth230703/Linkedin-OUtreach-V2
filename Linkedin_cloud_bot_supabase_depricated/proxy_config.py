"""
Simple proxy configuration for selenium-wire with IP whitelisting
"""
import os
from dotenv import load_dotenv

load_dotenv()

def get_proxy_options():
    """
    Get selenium-wire proxy options using IP whitelisting (no authentication)
    Returns proxy_options dict or None if proxy disabled
    """
    use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
    
    if not use_proxy:
        return None
    
    host = os.getenv("PROXY_HOST", "").strip()
    port = os.getenv("PROXY_PORT", "").strip()
    username = os.getenv("PROXY_USERNAME", "").strip()
    password = os.getenv("PROXY_PASSWORD", "").strip()
    
    if not all([host, port]):
        return None
    
    # Configure proxy string
    if username and password:
        from urllib.parse import quote
        encoded_user = quote(username, safe='')
        encoded_pass = quote(password, safe='')
        proxy_string = f'http://{encoded_user}:{encoded_pass}@{host}:{port}'
        https_proxy_string = f'https://{encoded_user}:{encoded_pass}@{host}:{port}'
    else:
        proxy_string = f'http://{host}:{port}'
        https_proxy_string = f'https://{host}:{port}'

    proxy_options = {
        'proxy': {
            'http': proxy_string,
            'https': https_proxy_string,
        }
    }
    
    return proxy_options