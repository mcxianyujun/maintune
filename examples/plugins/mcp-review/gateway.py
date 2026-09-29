# SPDX-License-Identifier: MIT
"""Private single-user Streamable HTTP bridge; no Maintune admin credentials."""

from __future__ import annotations

import argparse
import hmac
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIMIT = 256 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(config):
    endpoint = urllib.parse.urlsplit(config["maintune_url"])
    if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("Invalid Maintune URL")
    if endpoint.scheme == "http" and endpoint.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS for a remote Maintune instance")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", config[key]) for key in ("path_secret", "access_token")):
        raise ValueError("Use independently generated 32-byte URL-safe secrets")
    if config["path_secret"] == config["access_token"]:
        raise ValueError("Gateway and plugin secrets must differ")
    if config.get("bind", "127.0.0.1") != "127.0.0.1":
        raise ValueError("Bind to loopback and use a TLS reverse proxy or secure tunnel")


def make_server(config, port=None):
    validate_config(config)
    expected_path = "/" + config["path_secret"] + "/mcp"
    upstream = config["maintune_url"].rstrip("/") + "/api/plugins/nanaseinori.mcp-review/public/mcp"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    capacity = threading.BoundedSemaphore(16)

    class Handler(BaseHTTPRequestHandler):
        server_version = "WebReviewGateway"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):
            # Default access logs contain the credential-bearing request path.
            pass

        def respond(self, status, data=b""):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def authorized(self):
            if not hmac.compare_digest(self.path.encode(), expected_path.encode()):
                self.respond(404)
                return False
            # Remote MCP clients do not need browser CORS. Reject all Origin headers.
            if self.headers.get("Origin") is not None:
                self.respond(403)
                return False
            return True

        def do_GET(self):
            if self.authorized():
                self.respond(405)

        do_DELETE = do_GET
        do_OPTIONS = do_GET

        def do_POST(self):
            if not self.authorized():
                return
            if self.headers.get_content_type() != "application/json":
                self.respond(415)
                return
            if self.headers.get("MCP-Protocol-Version", "2025-03-26") not in ("2025-03-26", "2025-06-18", "2025-11-25"):
                self.respond(400)
                return
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                self.respond(411)
                return
            size = int(lengths[0])
            if size > LIMIT:
                self.respond(413)
                return
            if not capacity.acquire(blocking=False):
                self.respond(503)
                return
            try:
                body = self.rfile.read(size)
                if len(body) != size:
                    self.respond(400)
                    return
                request = urllib.request.Request(upstream, data=body, method="POST", headers={
                    "Content-Type": "application/json", "Authorization": "Bearer " + config["access_token"]})
                try:
                    reply = opener.open(request, timeout=40)
                except urllib.error.HTTPError as error:
                    reply = error
                with reply:
                    data = reply.read(LIMIT + 1)
                    if len(data) > LIMIT:
                        self.respond(502)
                    elif reply.code == 202:
                        self.respond(202)
                    elif reply.code == 200:
                        self.respond(200, data)
                    else:
                        # Do not relay host tracebacks, redirect locations or auth details.
                        self.respond(reply.code if reply.code in (400, 401, 403, 404, 413, 429) else 502)
            except (OSError, ValueError):
                self.respond(502)
            finally:
                capacity.release()

    class BoundedServer(ThreadingHTTPServer):
        connections = threading.BoundedSemaphore(32)

        def process_request(self, request, client_address):
            if not self.connections.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                self.connections.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.connections.release()

    return BoundedServer(("127.0.0.1", config.get("port", 8787) if port is None else port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).parent / ".private" / "gateway.json"))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    server = make_server(config)
    print("MCP gateway listening on loopback port", server.server_port, flush=True)
    print("Connection details are in .private/connection.txt; keep them private.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
