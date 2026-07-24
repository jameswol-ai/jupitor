import subprocess
import threading
import time
import requests
from http.server import BaseHTTPRequestHandler
import sys
import os
import urllib.parse

# Start Streamlit in a background thread
def start_streamlit():
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py",
         "--server.port", "8501",
         "--server.headless", "true",
         "--server.enableCORS", "false",
         "--server.enableXsrfProtection", "false",
         "--server.enableWebsocketCompression", "false",
         "--browser.gatherUsageStats", "false"],
        cwd="/var/task"  # Vercel’s working dir
    )
    # Give it a moment to start
    time.sleep(5)

# Proxy request to the local Streamlit instance
def proxy(request_path, query_string):
    try:
        url = f"http://localhost:8501{request_path}"
        if query_string:
            url += "?" + query_string
        resp = requests.get(url, timeout=5)
        return resp.status_code, resp.headers.get("content-type", "text/html"), resp.content
    except Exception as e:
        return 500, "text/plain", f"Streamlit not running: {e}".encode()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        status, content_type, body = proxy(parsed.path, parsed.query)
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.end_headers()
        self.wfile.write(body)

    # Ignore other methods (POST will also come as GET for static view)
    def do_POST(self):
        self.do_GET()

# Start Streamlit when module is loaded
if __name__ != "__main__":
    threading.Thread(target=start_streamlit, daemon=True).start()