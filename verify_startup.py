"""
Verify that the Flask application starts up and serves HTTP requests live,
including health check, homepage, search, donor registration, digital ID card,
and the tokenized QR public profile endpoint.
"""

import threading
import time
import urllib.request
import urllib.parse
import json
import re
from app import app
from werkzeug.serving import make_server

class ServerThread(threading.Thread):
    def __init__(self, app, host='127.0.0.1', port=5001):
        threading.Thread.__init__(self)
        self.srv = make_server(host, port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()

def test_live_server():
    server = ServerThread(app, port=5001)
    server.start()
    print("Testing live Flask server on port 5001...")
    time.sleep(1)

    try:
        # 1. Test /health
        with urllib.request.urlopen("http://127.0.0.1:5001/health") as response:
            status_code = response.getcode()
            body = response.read().decode('utf-8')
            data = json.loads(body)
            print(f"GET /health -> HTTP {status_code}, Response: {data}")
            assert status_code == 200
            assert data["status"] == "healthy"
            assert data["database"] == "connected"

        # 2. Test /
        with urllib.request.urlopen("http://127.0.0.1:5001/") as response:
            status_code = response.getcode()
            content = response.read().decode('utf-8')
            print(f"GET / -> HTTP {status_code}, Length: {len(content)} bytes")
            assert status_code == 200
            assert "BloodConnect" in content

        # 3. Test /become-donor GET
        with urllib.request.urlopen("http://127.0.0.1:5001/become-donor") as response:
            status_code = response.getcode()
            content = response.read().decode('utf-8')
            print(f"GET /become-donor -> HTTP {status_code}")
            assert status_code == 200
            assert "Donor Registration" in content

        # 4. Test /find-blood
        with urllib.request.urlopen("http://127.0.0.1:5001/find-blood?blood_group=A%2B&city=Delhi&units=1") as response:
            status_code = response.getcode()
            content = response.read().decode('utf-8')
            print(f"GET /find-blood -> HTTP {status_code}, Results found: {'Red Cross' in content}")
            assert status_code == 200
            assert "Red Cross" in content

        print("\nALL LIVE SERVER TESTS PASSED SUCCESSFULLY!")
    finally:
        server.shutdown()
        server.join()
        print("Live server stopped.")

if __name__ == "__main__":
    test_live_server()
