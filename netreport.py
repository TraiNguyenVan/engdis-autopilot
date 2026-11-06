"""Group captured calls into an endpoint map with representative bodies.

Usage: python3 netreport.py [net_calls.json]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def norm(u):
    p = re.sub(r"https?://[^/]+", "", u or "")
    p = re.sub(r"/\d{3,}", "/{id}", p)
    p = re.sub(r"[0-9a-f]{16,}", "{hash}", p)
    p = re.sub(r"\?_=.*$", "?_", p)
    return p


def main(path=None):
    path = path or os.path.join(HERE, "net_calls.json")
    calls = json.load(open(path, encoding="utf-8"))
    groups = {}
    for c in calls:
        key = ((c.get("m") or "GET").upper(), norm(c.get("u")))
        g = groups.setdefault(key, {"n": 0, "status": set(), "body": "", "resp": ""})
        g["n"] += 1
        if c.get("status"):
            g["status"].add(c["status"])
        if c.get("body") and not g["body"]:
            g["body"] = c["body"][:300]
        if c.get("resp") and not g["resp"]:
            g["resp"] = c["resp"][:300]
    for (m, p), g in sorted(groups.items(), key=lambda kv: (kv[0][0] == "GET", kv[0][1])):
        print(f"{m:5} {p[:90]:90} n={g['n']} st={sorted(g['status'], key=str)}")
        if g["body"]:
            print("      req:", g["body"].replace("\n", " ")[:160])
        if g["resp"]:
            print("      res:", g["resp"].replace("\n", " ")[:160])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
