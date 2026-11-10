#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy the workbench to GitHub Pages via api.github.com (no git binary needed).

Token is read from GH_PAT env var (preferred) or --token-stdin (one line via pipe).
It is NEVER written to disk, printed, or embedded in a remote URL.
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request

OWNER = "Abeginner111"
REPO = "daka-shouzhang"
BRANCH = "main"
API = "https://api.github.com"
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["index.html", "schema.sql"]


def req(method, path, token, body=None, dry=False):
    url = API + path
    if dry:
        brief = ""
        if body is not None:
            brief = " body=" + json.dumps(
                {k: ("<%d chars>" % len(v) if k == "content" else v)
                 for k, v in body.items()}, ensure_ascii=False)[:220]
        print("  [dry] %-6s %s%s" % (method, path, brief))
        return {"dry": True}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("X-GitHub-Api-Version", "2022-11-28")
    r.add_header("User-Agent", "workbuddy-pages-deploy")
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:700]
        raise RuntimeError("HTTP %s %s -> %s %s" % (method, path, e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("NETWORK %s %s -> %s" % (method, path, e.reason))


def get_token(args):
    t = os.environ.get("GH_PAT", "").strip()
    if not t and args.token_stdin:
        t = sys.stdin.readline().strip()
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    ap.add_argument("--token-stdin", action="store_true", help="read PAT as first line of stdin")
    args = ap.parse_args()

    token = get_token(args)
    if not args.dry_run and not token:
        print("ERROR: no PAT supplied. Set GH_PAT or pipe the token with --token-stdin.")
        return 2

    payloads = {}
    for name in FILES:
        p = os.path.join(HERE, name)
        raw = io.open(p, "rb").read()
        payloads[name] = base64.b64encode(raw).decode("ascii")
        print("file %-12s %7d bytes  -> base64 %d chars" % (name, len(raw), len(payloads[name])))

    print("\n=== STEP 1: repo check ===")
    repo = req("GET", "/repos/%s/%s" % (OWNER, REPO), token, dry=args.dry_run)
    if not args.dry_run:
        print("  %s | private=%s | default_branch=%s" %
              (repo["full_name"], repo["private"], repo["default_branch"]))
        if repo["private"]:
            print("  WARN: private repo -> GitHub Pages on free plan is NOT available.")
        if repo["default_branch"] != BRANCH:
            print("  WARN: default branch is %s, script targets %s" %
                  (repo["default_branch"], BRANCH))

    print("\n=== STEP 2: upload files ===")
    for name in FILES:
        path = "/repos/%s/%s/contents/%s" % (OWNER, REPO, name)
        sha = None
        if args.dry_run:
            req("GET", path + "?ref=" + BRANCH, token, dry=True)
        else:
            try:
                cur = req("GET", path + "?ref=" + BRANCH, token)
                sha = cur.get("sha")
                print("  %s exists, will update (sha %s...)" % (name, (sha or "")[:7]))
            except RuntimeError as e:
                if "-> 404 " in str(e):
                    print("  %s not present, will create" % name)
                else:
                    raise
        body = {
            "message": "Add love 100-things workbench" if name == "index.html"
                       else "Add Supabase schema + RLS",
            "content": payloads[name],
            "branch": BRANCH,
        }
        if sha:
            body["sha"] = sha
        out = req("PUT", path, token, body=body, dry=args.dry_run)
        if not args.dry_run:
            print("  uploaded %-12s commit %s" % (name, str(out.get("commit", {}).get("sha", ""))[:7]))

    print("\n=== STEP 3: enable GitHub Pages ===")
    pages_path = "/repos/%s/%s/pages" % (OWNER, REPO)
    source = {"branch": BRANCH, "path": "/"}
    if args.dry_run:
        req("GET", pages_path, token, dry=True)
        req("POST", pages_path, token, body={"source": source}, dry=True)
    else:
        enabled = False
        try:
            cur = req("GET", pages_path, token)
            enabled = True
            print("  Pages already enabled: %s" % cur.get("html_url", ""))
        except RuntimeError as e:
            if "-> 404 " not in str(e):
                raise
        if enabled:
            req("PATCH", pages_path, token, body={"source": source})
            print("  source ensured: %s / root" % BRANCH)
        else:
            try:
                req("POST", pages_path, token, body={"source": source})
                print("  Pages enabled: %s / root" % BRANCH)
            except RuntimeError as e:
                if "403" in str(e):
                    print("\n  PERMISSION DENIED: PAT needs 'Pages: Read and write' (fine-grained)")
                    print("  or 'repo' scope (classic). Fix the token and rerun; files are already uploaded.")
                elif "409" in str(e):
                    print("  already exists (409), continuing")
                else:
                    raise

    print("\n=== STEP 4: verify ===")
    if not args.dry_run:
        try:
            p = req("GET", pages_path, token)
            print("  site:   %s" % p.get("html_url", "?"))
            print("  status: %s | branch: %s | path: %s" %
                  (p.get("status", "?"),
                   p.get("source", {}).get("branch", "?"),
                   p.get("source", {}).get("path", "?")))
            print("  public_type: %s" % p.get("public", "?"))
        except RuntimeError as e:
            print("  could not confirm Pages: %s" % e)
        for name in FILES:
            try:
                f = req("GET", "/repos/%s/%s/contents/%s?ref=%s" % (OWNER, REPO, name, BRANCH), token)
                remote = base64.b64decode(f.get("content", ""))
                local = io.open(os.path.join(HERE, name), "rb").read()
                print("  %-12s remote=%d local=%d identical=%s" %
                      (name, len(remote), len(local), remote == local))
            except Exception as e:
                print("  %-12s verify failed: %s" % (name, e))
        print("\n  NOTE: first Pages build takes 1-2 minutes; open the URL afterwards.")
        print("  Next: open the site -> fill Supabase URL + publishable key in the config box.")
    else:
        req("GET", pages_path, token, dry=True)
        print("\n[dry-run] nothing was sent. Token present: %s" % ("yes" if token else "no"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
