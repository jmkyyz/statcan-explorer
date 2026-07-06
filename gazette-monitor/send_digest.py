#!/usr/bin/env python3
"""
Gazette digest sender.

Watches (via launchd WatchPaths) the outbox/ folder. When Claude's Monday
scheduled task drops a digest JSON here, this script emails it and archives
the file to sent/.

Outbox file format (one .json per digest):
    {"subject": "...", "html": "<html body>", "text": "optional plain-text fallback"}

Credentials: read from ~/statcan-explorer/.env (SMTP_HOST, SMTP_PORT,
SMTP_USER, SMTP_PASS, NOTIFY_TO) — same file the other jobs use.

Install:
    cp com.jasonkirby.gazette-digest.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.jasonkirby.gazette-digest.plist
"""
import json
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTBOX = HERE / "outbox"
SENT = HERE / "sent"
ENV_FILE = HERE.parent / ".env"
APP_PASSWORD_RTF = Path("/Users/jasonkirby/Desktop/StatCanApp/gmail_app_password.txt.rtf")

FROM_DEFAULT = "jmk.yyz.data@gmail.com"
TO_DEFAULT = "jasonkirby@gmail.com"


def load_env(path):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # Treat the unfilled template as absent.
    if env.get("SMTP_USER", "").startswith("you@"):
        env.pop("SMTP_USER", None)
        env.pop("SMTP_PASS", None)
    if env.get("NOTIFY_TO", "").startswith("you@"):
        env.pop("NOTIFY_TO", None)
    # Fall back to the same RTF app-password file the other jobs use.
    if not env.get("SMTP_PASS"):
        env["SMTP_USER"] = env.get("SMTP_USER") or FROM_DEFAULT
        env["SMTP_PASS"] = get_app_password()
    return env


def get_app_password():
    # Same extraction logic as ev_change_detector.py / send_statcan_daily.py.
    content = APP_PASSWORD_RTF.read_text()
    for line in reversed(content.split("\n")):
        clean = re.sub(r"\\[a-z]+\d*\s?", "", line)
        clean = re.sub(r"[{}]", "", clean).strip()
        candidate = clean.replace(" ", "")
        if len(candidate) == 16 and candidate.isalpha():
            return candidate
    raise ValueError(f"Could not extract a 16-char password from {APP_PASSWORD_RTF}")


def send(env, subject, html, text):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = env["SMTP_USER"]
    msg["To"] = env.get("NOTIFY_TO") or TO_DEFAULT
    msg.attach(MIMEText(text or "This digest is best viewed as HTML.", "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(env.get("SMTP_HOST", "smtp.gmail.com"),
                      int(env.get("SMTP_PORT", 587)), timeout=30) as s:
        s.starttls()
        s.login(env["SMTP_USER"], env["SMTP_PASS"])
        s.send_message(msg)
    return msg["To"]


def main():
    stamp = datetime.now().isoformat(timespec="seconds")
    OUTBOX.mkdir(exist_ok=True)
    SENT.mkdir(exist_ok=True)

    pending = sorted(OUTBOX.glob("*.json"))
    if not pending:
        return  # WatchPaths also fires when we archive; nothing to do.

    env = load_env(ENV_FILE)
    for f in pending:
        try:
            payload = json.loads(f.read_text())
            to = send(env, payload["subject"], payload["html"], payload.get("text"))
            f.rename(SENT / f"{f.stem}.{datetime.now():%Y%m%d-%H%M%S}.json")
            print(f"[{stamp}] Sent '{payload['subject']}' to {to} ({f.name})")
        except Exception as e:
            print(f"[{stamp}] FAILED on {f.name}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            # Leave file in outbox so the next trigger retries it.


if __name__ == "__main__":
    main()
