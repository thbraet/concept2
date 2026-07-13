#!/usr/bin/env python3
"""Serve the rowing dashboard with a working "Refresh data" button.

Run:
    python3 serve.py

Then open http://localhost:8000/ (a browser tab opens automatically).
Clicking "Refresh data" re-fetches workouts from Concept2 and rebuilds the page.
"""

import subprocess
import sys
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
PORT = 8000


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("", "/"):
            self.path = "/dashboard.html"
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/refresh":
            self.send_error(404)
            return
        try:
            self._refresh()
        except Exception as e:  # noqa: BLE001 — surface any failure to the browser
            self._send(500, str(e))
        else:
            self._send(200, '{"ok": true}', ctype="application/json")

    def _refresh(self):
        """Re-fetch workouts, then regenerate dashboard.html."""
        for script in ("fetch_workouts.py", "build_dashboard.py"):
            proc = subprocess.run(
                [sys.executable, str(HERE / script)],
                cwd=HERE,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"{script} failed (exit {proc.returncode}):\n"
                    f"{proc.stdout}\n{proc.stderr}".strip()
                )

    def _send(self, code, body, ctype="text/plain"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    handler = partial(Handler, directory=str(HERE))
    httpd = HTTPServer(("localhost", PORT), handler)
    url = f"http://localhost:{PORT}/"
    print(f"Serving dashboard at {url}  (Ctrl-C to stop)")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
