#!/usr/bin/env python3
"""
EV Incentive Database Change Detector
Checks daily whether the open.canada.ca CKAN resource has been updated
and sends an email notification when it has.

Uses the same Gmail account and app-password RTF file as send_statcan_daily.py.

Schedule (Mac launchd):
  cp com.statcan.ev-change-detector.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.statcan.ev-change-detector.plist
"""

import json
import re
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests

RESOURCE_ID      = '4252857a-9e5f-47f9-98b1-1291e8f9f692'
API_URL          = f'https://open.canada.ca/data/en/api/3/action/resource_show?id={RESOURCE_ID}'
STATE_FILE       = Path(__file__).parent / '.ev_detector_state.json'
APP_PASSWORD_RTF = Path('/Users/jasonkirby/Desktop/StatCanApp/gmail_app_password.txt.rtf')

FROM_EMAIL = 'jmk.yyz.data@gmail.com'
TO_EMAIL   = 'jasonkirby@gmail.com'


def get_app_password():
    content = APP_PASSWORD_RTF.read_text()
    for line in reversed(content.split('\n')):
        clean = re.sub(r'\\[a-z]+\d*\s?', '', line)
        clean = re.sub(r'[{}]', '', clean).strip()
        candidate = clean.replace(' ', '')
        if len(candidate) == 16 and candidate.isalpha():
            return candidate
    raise ValueError(f'Could not extract a 16-char password from {APP_PASSWORD_RTF}')


def fetch_resource_meta():
    resp = requests.get(API_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(f'API error: {data}')
    r = data['result']
    return {
        'last_modified':      r.get('last_modified'),
        'date_published':     r.get('date_published'),
        'metadata_modified':  r.get('metadata_modified'),
    }


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_email(subject, body):
    password = get_app_password()
    msg = MIMEText(body, 'plain')
    msg['Subject'] = subject
    msg['From']    = FROM_EMAIL
    msg['To']      = TO_EMAIL

    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(FROM_EMAIL, password)
        smtp.send_message(msg)
    print(f'  ✉️  Email sent to {TO_EMAIL}')


def main():
    print(f'[{datetime.now().isoformat(timespec="seconds")}] Checking EV incentive database…')

    try:
        meta = fetch_resource_meta()
    except Exception as exc:
        print(f'  ❌  Failed to fetch metadata: {exc}')
        sys.exit(1)

    state    = load_state()
    prev_mod = state.get('last_modified')
    curr_mod = meta.get('last_modified')

    print(f'  Previous last_modified: {prev_mod}')
    print(f'  Current  last_modified: {curr_mod}')

    if prev_mod and curr_mod == prev_mod:
        print('  No change detected.')
    else:
        if prev_mod is None:
            print('  First run — saving baseline state.')
        else:
            print('  🆕  Change detected! Sending notification…')
            subject = '🚗 EV Incentive Data Updated'
            body = (
                f'The open.canada.ca EV Affordability incentive dataset has been updated.\n\n'
                f'Previous last_modified : {prev_mod}\n'
                f'New last_modified      : {curr_mod}\n'
                f'Date published         : {meta.get("date_published")}\n\n'
                f'Dashboard: https://statcan-explorer.onrender.com/ev\n'
            )
            send_email(subject, body)

    save_state({**state, **meta, 'checked_at': datetime.utcnow().isoformat()})
    print('  State saved.')


if __name__ == '__main__':
    main()
