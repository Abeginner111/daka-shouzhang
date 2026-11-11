#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline end-to-end rehearsal of supabase_setup.py against a fake Management API."""
import io
import json
import os
import re
import sys
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

os.environ["no_proxy"] = "127.0.0.1,localhost"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["SUPABASE_ACCESS_TOKEN"] = "MOCK_TOKEN_NEVER_PRINT"

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = {"projects": [], "sql": [], "auth": {}, "health_calls": 0,
         "created": None, "db_pass": None, "keys_post": []}
REF = "abcdefghijklmnopqrst"


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

    def _body(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _route(self, method):
        u = urlparse(self.path)
        p, q = u.path, u.query
        b = self._body() if method in ("POST", "PATCH", "PUT") else None
        if p == "/v1/organizations" and method == "GET":
            return 200, [{"id": "org-1", "name": "Personal", "slug": "personal"}]
        if p == "/v1/projects" and method == "GET":
            return 200, STORE["projects"]
        if p == "/v1/projects" and method == "POST":
            STORE["db_pass"] = b.get("db_pass")
            STORE["created"] = {"id": REF, "name": b.get("name")}
            STORE["projects"].append(STORE["created"])
            return 201, STORE["created"]
        if re.fullmatch(r"/v1/projects/[^/]+/health", p) and method == "GET":
            STORE["health_calls"] += 1
            return 200, {"healthy": True, "services": [{"name": "auth", "status": "ACTIVE_HEALTHY"}]}
        if re.fullmatch(r"/v1/projects/[^/]+/database/query", p) and method == "POST":
            STORE["sql"].append(b.get("query", ""))
            if "information_schema" in b.get("query", ""):
                return 200, [{"table_name": "love_config"}, {"table_name": "love_items"}]
            return 200, []
        if re.fullmatch(r"/v1/projects/[^/]+/config/auth", p) and method == "PATCH":
            STORE["auth"].update(b)
            return 200, STORE["auth"]
        if re.fullmatch(r"/v1/projects/[^/]+/config/auth", p) and method == "GET":
            return 200, STORE["auth"]
        if re.fullmatch(r"/v1/projects/[^/]+/api-keys", p) and method == "GET":
            return 200, [
                {"name": "anon", "type": "legacy", "api_key": "MOCK_ANON_KEY"},
                {"name": "service_role", "type": "secret", "api_key": "MOCK_SECRET_NEVER_PRINT"},
                {"name": "publishable", "type": "publishable", "api_key": "MOCK_PUBLISHABLE_KEY"},
            ]
        if re.fullmatch(r"/v1/projects/[^/]+/api-keys", p) and method == "POST":
            STORE["keys_post"].append(b)
            return 201, {"api_key": "MOCK_PUBLISHABLE_KEY"}
        return 404, {"message": "not found: %s %s" % (method, p)}

    def do_GET(self):
        c, o = self._route("GET")
        self._send(c, o)

    def do_POST(self):
        c, o = self._route("POST")
        self._send(c, o)

    def do_PATCH(self):
        c, o = self._route("PATCH")
        self._send(c, o)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

import supabase_setup  # noqa: E402
supabase_setup.API = "http://127.0.0.1:%d" % port
sys.argv = ["supabase_setup.py"]
buf = io.StringIO()
with redirect_stdout(buf):
    rc = supabase_setup.main()
srv.shutdown()
out = buf.getvalue()
print(out)

print("=== MOCK ASSERTIONS ===")
ok = True
local_sql = io.open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read()
checks = [
    ("project created", STORE["created"] is not None),
    ("schema.sql sent intact", bool(STORE["sql"]) and STORE["sql"][0] == local_sql),
    ("tables verified", len(STORE["sql"]) >= 2),
    ("autoconfirm on", STORE["auth"].get("mailer_autoconfirm") is True),
    ("site url set", STORE["auth"].get("site_url") == "https://Abeginner111.github.io/daka-shouzhang/"),
    ("publishable key selected", "MOCK_PUBLISHABLE_KEY" in out),
    ("no secret key printed", "MOCK_SECRET_NEVER_PRINT" not in out),
    ("no token printed", "MOCK_TOKEN_NEVER_PRINT" not in out),
    ("no db password printed", STORE["db_pass"] and STORE["db_pass"] not in out),
    ("project url correct", "https://%s.supabase.co" % REF in out),
    ("exit 0", rc == 0),
]
for name, val in checks:
    print("  %-28s %s" % (name, "PASS" if val else "FAIL"))
    ok &= bool(val)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
