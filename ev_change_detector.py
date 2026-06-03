#!/usr/bin/env python3
"""
EV Incentive Database Change Detector
Checks daily whether the open.canada.ca CKAN resource has been updated
and sends an email notification when it has.

Setup:
  pip install requests python-dotenv
  cp .env.example .env   # fill in your SMTP credentials
  python ev_change_detector.py

Schedule (Mac launchd):
  See com.statcan.ev-change-detector.plist for daily scheduling.
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

RESOURCE_ID = '4252857a-9e5f-47f9-98b1-1291e8f9f692'
API_URL     = f'https://open.canada.ca/data/en/api/3/action/resource_show?id={RESOURCE_ID}'
STATE_FILE  = Path(__file__).parent / '.ev_detector_state.json'

# ── Email config (from .env) ────────────────────────────────────────────────
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
NOTIFY_TO = os.environ.get('NOTIFY_TO', SMTP_USER)


def fetch_resource_meta():
    resp = requests.get(API_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(f"API error: {data}")
    r = data['result']
    return {
        'last_modified':   r.get('last_modified'),
        'date_published':  r.get('date_published'),
        'metadata_modified': r.get('metadata_modified'),
    }


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_email(subject, body):
    if not SMTP_USER or not SMTP_PASS:
        print('⚠️  SMTP credentials not configured — skipping email.')
        print(f'   Subject: {subject}')
        print(f'   Body: {body}')
        return

    msg = MIMEText(body, 'plain')
    msg['Subject'] = subject
    msg['From']    = SMTP_USER
    msg['To']      = NOTIFY_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)
    print(f'✉️  Email sent to {NOTIFY_TO}')


def main():
    print(f'[{datetime.now().isoformat(timespec="seconds")}] Checking EV incentive database…')

    try:
        meta = fetch_resource_meta()
    except Exception as exc:
        print(f'❌  Failed to fetch metadata: {exc}')
        sys.exit(1)

    state     = load_state()
    prev_mod  = state.get('last_modified')
    curr_mod  = meta.get('last_modified')

    print(f'   Previous last_modified: {prev_mod}')
    print(f'   Current  last_modified: {curr_mod}')

    if prev_mod and curr_mod and curr_mod == prev_mod:
        print('   No change detected.')
    else:
        if prev_mod is None:
            print('   First run — saving baseline state.')
        else:
            print(f'   🆕  Change detected! Sending notification…')
            subject = '🚗 EV Incentive Data Updated'
            body = (
                f'The open.canada.ca EV Affordability incentive dataset has been updated.\n\n'
                f'Previous last_modified : {prev_mod}\n'
                f'New last_modified      : {curr_mod}\n'
                f'Date published         : {meta.get("date_published")}\n\n'
                f'Dashboard: https://statcan-explorer.onrender.com/ev\n'
                f'API resource: https://open.canada.ca/data/en/dataset?id={RESOURCE_ID}\n'
            )
            send_email(subject, body)

    save_state({**state, **meta, 'checked_at': datetime.utcnow().isoformat()})
    print('   State saved.')


if __name__ == '__main__':
    main()
