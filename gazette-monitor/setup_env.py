#!/usr/bin/env python3
"""One-time setup: extract the Gmail app password from the Desktop RTF and
write real values into ~/statcan-explorer/.env, so background launchd jobs
don't need Desktop access. Run from Terminal:  python3 setup_env.py"""
import re
from pathlib import Path

RTF = Path("/Users/jasonkirby/Desktop/StatCanApp/gmail_app_password.txt.rtf")
ENV = Path.home() / "statcan-explorer" / ".env"

content = RTF.read_text()
password = None
for line in reversed(content.split("\n")):
    clean = re.sub(r"\\[a-z]+\d*\s?", "", line)
    clean = re.sub(r"[{}]", "", clean).strip()
    candidate = clean.replace(" ", "")
    if len(candidate) == 16 and candidate.isalpha():
        password = candidate
        break
if not password:
    raise SystemExit(f"Could not extract a 16-char password from {RTF}")

ENV.write_text(
    "# Real credentials — this file is gitignored. Written by setup_env.py.\n"
    "SMTP_HOST=smtp.gmail.com\n"
    "SMTP_PORT=587\n"
    "SMTP_USER=jmk.yyz.data@gmail.com\n"
    f"SMTP_PASS={password}\n"
    "NOTIFY_TO=jasonkirby@gmail.com\n"
)
print(f"Wrote {ENV} (password length {len(password)}) — done.")
