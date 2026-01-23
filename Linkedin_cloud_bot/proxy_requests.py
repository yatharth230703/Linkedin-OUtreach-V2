"""
Proxy-enabled requests session for API calls
Uses iProyal proxy with IP whitelisting for all HTTP requests
"""
import os
import requests
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
        
        host = os.getenv("PROXY_HOST")
        port = os.getenv("PROXY_PORT")
        
        if not all([host, port]):
            return
        
        # Configure proxy for requests (IP whitelisted, no auth needed)
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