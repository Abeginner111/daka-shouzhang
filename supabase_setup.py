#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot Supabase setup for the love-100-things workbench.

Uses the Supabase Management API only (no browser, no CLI, no SDK).
Token comes from SUPABASE_ACCESS_TOKEN env var or --token-stdin (one line).
The token, generated db password and service_role key are NEVER printed
or written to disk. Only the public Project URL + publishable key are output.
"""
import argparse
import io
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request

API = "https://api.supabase.com"
SITE = "https://Abeginner111.github.io/daka-shouzhang/"
PROJECT_NAME = "love-100-things"
HERE = os.path.dirname(os.path.abspath(__file__))


def req(method, path, token, body=None, dry=False, timeout=45):
    url = API + path
    if dry:
        brief = ""
        if body is not None:
            brief = " body=" + json.dumps(
                {k: ("<%d chars>" % len(str(v)) if k in ("query", "db_pass") else v)
                 for k, v in body.items()}, ensure_ascii=False)[:240]
        print("  [dry] %-6s %s%s" % (method, path, brief))
        return {"dry": True}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Content-Type", "application/json")
    r.add_header("Accept", "application/json")
    r.add_header("User-Agent", "workbuddy-supabase-setup")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        detail = re.sub(r"sbp_[A-Za-z0-9_]+", "<redacted>", detail)
        if token:
            detail = detail.replace(token, "<redacted>")
        raise RuntimeError("HTTP %s %s -> %s %s" % (method, path, e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("NETWORK %s %s -> %s" % (method, path, e.reason))


def as_list(x, *names):
    """Management API sometimes wraps arrays in an object."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for n in names:
            if isinstance(x.get(n), list):
                return x[n]
        return []
    return []


def get_token(args):
    t = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if not t and args.token_stdin:
        t = sys.stdin.readline().strip()
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--token-stdin", action="store_true")
    ap.add_argument("--existing-ref", default="", help="reuse an existing project ref, skip creation")
    args = ap.parse_args()

    token = get_token(args)
    if not args.dry_run and not token:
        print("ERROR: no Supabase access token. Set SUPABASE_ACCESS_TOKEN or use --token-stdin.")
        return 2

    sql = io.open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read()
    print("schema.sql: %d chars" % len(sql))

    print("\n=== STEP 1: organization / project ===")
    ref = args.existing_ref.strip()
    if ref:
        print("  reuse existing project ref (skip creation)")
    else:
        orgs = req("GET", "/v1/organizations", token, dry=args.dry_run)
        if not args.dry_run:
            orgs = as_list(orgs, "organizations", "data")
            if not orgs:
                print("  no organization yet, creating one")
                new_org = req("POST", "/v1/organizations", token, body={"name": "Personal"})
                print("  organization created: %s" % new_org.get("name", "?"))
                orgs = [new_org]
            org = orgs[0]
            print("  organization: %s (%s)" % (org.get("name", "?"), org.get("id", "?")))
            projects = as_list(req("GET", "/v1/projects", token), "projects", "data")
            print("  existing projects: %d" % len(projects))
            reuse = next((p for p in projects if p.get("name") == PROJECT_NAME), None)
            if reuse:
                ref = reuse.get("id") or reuse.get("ref")
                print("  found existing project %s, reuse" % ref)
            else:
                db_pass = secrets.token_urlsafe(30)
                body = {
                    "name": PROJECT_NAME,
                    "organization_slug": org.get("slug") or org.get("id"),
                    "db_pass": db_pass,
                    "region_selection": {"type": "smartGroup", "code": "apac"},
                }
                try:
                    created = req("POST", "/v1/projects", token, body=body, timeout=90)
                except RuntimeError as e:
                    if "400" in str(e) or "422" in str(e):
                        body.pop("region_selection", None)
                        body.pop("organization_slug", None)
                        body["organization_id"] = org.get("id")
                        body["region"] = "ap-southeast-1"
                        print("  primary payload rejected, retry with organization_id + ap-southeast-1")
                        created = req("POST", "/v1/projects", token, body=body, timeout=90)
                    else:
                        raise
                ref = created.get("id") or created.get("ref")
                if not ref:
                    print("  ERROR: create returned no project ref: %s" % json.dumps(created)[:200])
                    return 3
                print("  project created: %s" % ref)

    print("\n=== STEP 2: wait for services ===")
    if not args.dry_run:
        healthy = False
        for i in range(36):
            try:
                h = req("GET", "/v1/projects/%s/health" % ref, token)
                text = json.dumps(h, ensure_ascii=False)
                if "ACTIVE_HEALTHY" in text or '"healthy": true' in text or '"healthy":true' in text:
                    healthy = True
                    break
            except RuntimeError:
                pass
            time.sleep(5)
        print("  services ready: %s%s" % (healthy, "" if healthy else " (timed out, continuing)"))
    else:
        req("GET", "/v1/projects/%s/health" % (ref or "{ref}"), token, dry=True)

    print("\n=== STEP 3: run schema.sql ===")
    req("POST", "/v1/projects/%s/database/query" % (ref or "{ref}"), token,
        body={"query": sql}, dry=args.dry_run, timeout=90)
    if not args.dry_run:
        try:
            check = req("POST", "/v1/projects/%s/database/query" % ref, token,
                        body={"query": "select table_name from information_schema.tables "
                                       "where table_schema='public' and table_name in "
                                       "('love_items','love_config') order by 1;"})
            print("  tables present: %s" % json.dumps(check, ensure_ascii=False)[:220])
        except RuntimeError as e:
            print("  table read-back skipped: %s" % str(e)[:180])

    print("\n=== STEP 4: auth config (autoconfirm + site URL) ===")
    auth_body = {
        "mailer_autoconfirm": True,
        "site_url": SITE,
        "uri_allow_list": SITE,
    }
    req("PATCH", "/v1/projects/%s/config/auth" % (ref or "{ref}"), token,
        body=auth_body, dry=args.dry_run)
    if not args.dry_run:
        try:
            cur = req("GET", "/v1/projects/%s/config/auth" % ref, token)
            print("  mailer_autoconfirm = %s | site_url = %s" %
                  (cur.get("mailer_autoconfirm"), cur.get("site_url")))
        except RuntimeError as e:
            print("  config read-back skipped: %s" % str(e)[:180])

    print("\n=== STEP 5: fetch public API key ===")
    keys = req("GET", "/v1/projects/%s/api-keys?reveal=true" % (ref or "{ref}"), token,
               dry=args.dry_run)
    if args.dry_run:
        print("\n[dry-run] nothing was sent.")
        return 0
    keys = as_list(keys, "keys", "api_keys", "data")
    pub = None
    for k in keys:
        if k.get("type") == "publishable" or k.get("name") == "publishable":
            pub = k.get("api_key")
            break
    if not pub:
        pub = next((k.get("api_key") for k in keys if k.get("name") == "anon"), None)
    if not pub:
        print("  no publishable/anon key yet, creating one")
        made = req("POST", "/v1/projects/%s/api-keys" % ref, token,
                   body={"type": "publishable", "name": "default"})
        pub = made.get("api_key")
        if not pub:
            keys = as_list(req("GET", "/v1/projects/%s/api-keys?reveal=true" % ref, token),
                           "keys", "api_keys", "data")
            pub = next((k.get("api_key") for k in keys
                        if k.get("type") == "publishable" or k.get("name") == "anon"), None)
    project_url = "https://%s.supabase.co" % ref

    print("\n=== RESULT (these two values are public by design) ===")
    print("  Project URL      : %s" % project_url)
    print("  publishable key  : %s" % pub)
    print("\n  Paste them into the site's config box, or send them to me so I can")
    print("  run an end-to-end write/read verification. Do NOT paste a secret key.")
    return 0 if pub else 1


if __name__ == "__main__":
    sys.exit(main())
