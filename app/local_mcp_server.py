"""Local Python HTTP server for MCP. Binds only to 127.0.0.1."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .mcp_protocol import lambda_handler


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/mcp":
            self.send_error(404)
            return
        if Path("outage.flag").exists():
            self.send_response(503)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        result = lambda_handler({"httpMethod": "POST", "body": body,
                                 "headers": dict(self.headers)}, None)
        self.send_response(result["statusCode"])
        for key, value in result.get("headers", {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(result.get("body", "").encode("utf-8"))


if __name__ == "__main__":
    print("MCP sandbox server at http://127.0.0.1:8765/mcp")
    print("Simulate outage: create a file named outage.flag in this directory")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
