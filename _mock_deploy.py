#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline end-to-end rehearsal of deploy.py against a local fake GitHub API.

Two scenarios are covered:
  A) site not live yet, files already exist -> PUT must carry sha, Pages enabled
  B) site already live, files already exist -> PUT must carry sha, Pages API skipped
Also verifies base64 payload == local bytes, auth headers, and no secret leakage.
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
STORE = {"files": {}, "pages": None, "auth": [], "puts": [], "post": [], "patch": []}


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
        p = urlparse(self.path).path
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
        STORE["auth"].append(self.headers.get("Authorization", ""))
        STORE["puts"].append((p, b))
        name = p.rsplit("/", 1)[-1]
        STORE["files"][name] = b["content"]
        return self._send(201, {"commit": {"sha": "a1b2c3d4e5f6"}})

    def do_POST(self):
        p = urlparse(self.path).path
        b = self._body()
        STORE["auth"].append(self.headers.get("Authorization", ""))
        STORE["post"].append((p, b))
        if p == PREFIX + "/pages":
            STORE["pages"] = {"html_url": "https://Abeginner111.github.io/daka-shouzhang/",
                              "status": "built", "source": b.get("source"), "public": True}
            return self._send(201, STORE["pages"])
        return self._send(404, {"message": "Not Found"})

    def do_PATCH(self):
        p = urlparse(self.path).path
        b = self._body()
        STORE["auth"].append(self.headers.get("Authorization", ""))
        STORE["patch"].append((p, b))
        return self._send(200, {"source": b.get("source")})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

import deploy  # noqa: E402
deploy.API = "http://127.0.0.1:%d" % port
deploy.verify_live_content = lambda: None

ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print("  %-46s %s" % (label, "PASS" if cond else "FAIL"))


def scenario(title, live):
    global STORE
    STORE = {"files": {}, "pages": None, "auth": [], "puts": [], "post": [], "patch": []}
    STORE["files"]["index.html"] = base64.b64encode(b"OLD INDEX").decode()
    STORE["files"]["schema.sql"] = base64.b64encode(b"OLD SQL").decode()
    deploy.site_is_live = lambda: live
    sys.argv = ["deploy.py"]
    print("\n=== %s ===" % title)
    rc = deploy.main()
    check("script exit code 0", rc == 0)
    for name in deploy.FILES:
        remote = base64.b64decode(STORE["files"][name])
        local = io.open(os.path.join(HERE, name), "rb").read()
        check("%s uploaded bytes identical" % name, remote == local)
    puts = {p.rsplit("/", 1)[-1]: b for p, b in STORE["puts"]}
    check("both files updated (not created)", len(puts) == 2)
    check("PUT carries sha for existing files",
          all(puts.get(n, {}).get("sha") == "mocksha" + n for n in deploy.FILES))
    check("all requests authorized",
          all(a.startswith("Bearer ") for a in STORE["auth"]))
    if live:
        check("Pages API skipped when site is live",
              len(STORE["post"]) == 0 and len(STORE["patch"]) == 0)
    else:
        src = STORE["pages"]["source"] if STORE["pages"] else None
        check("Pages enabled with main/root", src == {"branch": "main", "path": "/"})
    check("mock token never appears in request bodies",
          "MOCK_TOKEN_SHOULD_NEVER_PRINT" not in json.dumps(STORE["puts"]))


scenario("A: site not live, files exist", False)
scenario("B: site already live, files exist", True)

srv.shutdown()
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
