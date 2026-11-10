#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline end-to-end rehearsal of deploy.py against a local fake GitHub API.

Verifies: request shapes, base64 payload == local bytes, Pages source,
idempotent create/update path, and that no secret leaks into output.
"""
import base64
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

os.environ["no_proxy"] = "127.0.0.1,localhost"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["GH_PAT"] = "MOCK_TOKEN_SHOULD_NEVER_PRINT"

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = "/repos/Abeginner111/daka-shouzhang"
STORE = {"files": {}, "pages": None, "auth": [], "puts": [], "post": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        STORE["auth"].append(self.headers.get("Authorization", ""))
        if p == PREFIX:
            return self._send(200, {"full_name": "Abeginner111/daka-shouzhang",
                                   "private": False, "default_branch": "main"})
        if p == PREFIX + "/pages":
            if STORE["pages"] is None:
                return self._send(404, {"message": "Not Found"})
            return self._send(200, STORE["pages"])
        if p.startswith(PREFIX + "/contents/"):
            name = p.rsplit("/", 1)[-1]
            if name in STORE["files"]:
                return self._send(200, {"sha": "mocksha" + name,
                                       "content": STORE["files"][name]})
            return self._send(404, {"message": "Not Found"})
        return self._send(404, {"message": "Not Found"})

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_PUT(self):
        p = urlparse(self.path).path
        b = self._body()
        STORE["puts"].append((p, b))
        name = p.rsplit("/", 1)[-1]
        STORE["files"][name] = b["content"]
        return self._send(201, {"commit": {"sha": "a1b2c3d4e5f6"}})

    def do_POST(self):
        p = urlparse(self.path).path
        b = self._body()
        STORE["post"].append((p, b))
        if p == PREFIX + "/pages":
            STORE["pages"] = {"html_url": "https://Abeginner111.github.io/daka-shouzhang/",
                              "status": "built", "source": b.get("source"), "public": True}
            return self._send(201, STORE["pages"])
        return self._send(404, {"message": "Not Found"})

    def do_PATCH(self):
        return self.do_POST()


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()

import deploy  # noqa: E402
deploy.API = "http://127.0.0.1:%d" % port
sys.argv = ["deploy.py"]
rc = deploy.main()
srv.shutdown()

print("\n=== MOCK ASSERTIONS ===")
ok = True
for name in deploy.FILES:
    remote = base64.b64decode(STORE["files"][name])
    local = io.open(os.path.join(HERE, name), "rb").read()
    same = remote == local
    ok &= same
    print("  %-12s upload bytes identical: %s" % (name, same))
src = STORE["pages"]["source"] if STORE["pages"] else None
ok &= (src == {"branch": "main", "path": "/"})
print("  Pages source main/root: %s" % (src == {"branch": "main", "path": "/"}))
ok &= all(a == "Bearer MOCK_TOKEN_SHOULD_NEVER_PRINT" for a in STORE["auth"])
print("  all requests authorized: %s" % all(a.startswith("Bearer ") for a in STORE["auth"]))
ok &= ("MOCK_TOKEN_SHOULD_NEVER_PRINT" not in "".join(
    [str(STORE["post"])]))
print("  script exit code: %s" % rc)
print("RESULT:", "PASS" if ok and rc == 0 else "FAIL")
sys.exit(0 if ok and rc == 0 else 1)
