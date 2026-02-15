import requests
from urllib.parse import urlparse
import os

def download_dom(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        parsed_url = urlparse(url)
        filename = parsed_url.netloc.replace(".", "_")

        # Add path to filename if it exists
        if parsed_url.path and parsed_url.path != "/":
            path_part = parsed_url.path.strip("/").replace("/", "_")
            filename += "_" + path_part

        filename += ".html"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(response.text)

        print(f"[✓] Saved: {filename}")

    except requests.exceptions.RequestException as e:
        print(f"[✗] Failed: {url} -> {e}")


if __name__ == "__main__":
    urls = [
        "https://legora.com/security",
        "https://legora.com/careers",
        "https://legora.com/about",
        "https://legora.com/contact-us"
    ]

    for url in urls:
        download_dom(url)