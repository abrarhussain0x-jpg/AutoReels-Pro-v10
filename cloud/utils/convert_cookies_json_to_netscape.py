#!/usr/bin/env python3
"""Convert exported browser cookies JSON (list of cookie objects)
to Netscape cookies.txt format usable by yt-dlp/yt-dlp --cookies.

Usage:
    python convert_cookies_json_to_netscape.py input.json output.txt

Do NOT commit real cookies to the repo; keep them as a secret and
write them into the runner at runtime.
"""
import json
import sys
from pathlib import Path


def to_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File", "# This file was generated from JSON; keep it private"]
    for c in cookies:
        domain = c.get("domain", "")
        host_only = c.get("hostOnly", False)
        if not host_only and not domain.startswith("."):
            domain = "." + domain
        flag = "TRUE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        exp = int(float(c.get("expirationDate", 0))) if c.get("expirationDate") else 0
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append("\t".join([domain, flag, path, secure, str(exp), name, value]))
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) < 3:
        print("Usage: convert_cookies_json_to_netscape.py input.json output.txt", file=sys.stderr)
        sys.exit(2)
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    data = json.loads(inp.read_text(encoding="utf-8"))
    # Expecting a list of cookie dicts
    content = to_netscape(data)
    out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
