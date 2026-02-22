import os
import requests
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

class ProxySession:
    """
    Requests session with automatic proxy configuration
    """
    
    def __init__(self):
        self.session = requests.Session()
        self._setup_proxy()
    
    def _setup_proxy(self):
        """Setup proxy configuration for requests session"""
        use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        
        if not use_proxy:
            return
        
        host = os.getenv("PROXY_HOST", "").strip()
        port = os.getenv("PROXY_PORT", "").strip()
        username = os.getenv("PROXY_USERNAME", "").strip()
        password = os.getenv("PROXY_PASSWORD", "").strip()
        
        if not all([host, port]):
            return
        
        # Configure proxy for requests with authentication if provided
        if username and password:
            # URL encode username and password to handle special characters
            encoded_user = quote(username, safe='')
            encoded_pass = quote(password, safe='')
            proxy_url = f"http://{encoded_user}:{encoded_pass}@{host}:{port}"
        else:
            # Fallback to IP whitelisting if no auth provided
            proxy_url = f"http://{host}:{port}"
        
        self.session.proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        
        # Set headers to mimic browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        })
    
    def get(self, url, **kwargs):
        """GET request with proxy"""
        return self.session.get(url, **kwargs)
    
    def post(self, url, **kwargs):
        """POST request with proxy"""
        return self.session.post(url, **kwargs)
    
    def put(self, url, **kwargs):
        """PUT request with proxy"""
        return self.session.put(url, **kwargs)
    
    def delete(self, url, **kwargs):
        """DELETE request with proxy"""
        return self.session.delete(url, **kwargs)
    
    def request(self, method, url, **kwargs):
        """Generic request with proxy"""
        return self.session.request(method, url, **kwargs)

# Global proxy session instance
proxy_session = ProxySession()

def get_proxy_session():
    """Get the global proxy-enabled requests session"""
    return proxy_session