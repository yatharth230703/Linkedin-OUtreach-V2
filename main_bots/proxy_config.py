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
    
    host = os.getenv("PROXY_HOST")
    port = os.getenv("PROXY_PORT")
    
    if not all([host, port]):
        return None
    
    # Use IP whitelisting - no authentication required
    # Try different format for selenium-wire
    proxy_options = {
        'proxy': {
            'http': f'http://{host}:{port}',
            'https': f'https://{host}:{port}',
        }
    }
    
    return proxy_options