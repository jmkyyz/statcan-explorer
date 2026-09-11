# Access request — OCL open-data bulk files behind a bot challenge

**Status:** draft, not sent. Send only if `check_sources.py` reports
`datastore_active=False` on both bulk resources (if either is DataStore-backed,
query the portal instead and no request is needed).

**Where to send it:** use the `maintainer_email` / `author_email` that
`check_sources.py` now prints for the two datasets — that is the contact the OCL
publishes on the dataset records themselves. Do not guess a generic inbox.

**Before sending, decide two things:**

1. *Affiliation.* The draft is written as an ordinary open-data user. Adding an
   employer may get a faster reply, but it turns a bug report into a media
   inquiry and will likely be routed to communications rather than to whoever
   administers the WAF. The technical route is usually quicker. Your call.
2. *Attachment.* The appendix is enough for a web administrator to reproduce it
   in one command. Keep it — a report that can be reproduced gets fixed; one
   that cannot gets closed.

---

**Subject:** Open-data bulk files for the Registry of Lobbyists returning HTTP 403 to automated clients

Hello,

I want to flag what looks like an unintended side-effect of a recent change to
the lobbycanada.gc.ca web infrastructure.

The Office publishes two datasets on the Government of Canada's open-data
portal:

- **Lobbying Registrations** — `70ef2117-1095-4d77-80eb-b87f2bada2a4`
- **Monthly Communication Reports** — `a34eb330-7136-4f5e-9f5f-3ba41df58b06`

Both records list their bulk files as resources hosted on your own server:

- `https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip`
- `https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip`

Since approximately **20 July 2026**, both URLs return **HTTP 403** with a
`cf-mitigated: challenge` header to any non-browser client. The files download
normally in a web browser, so the data has not been withdrawn — it has become
inaccessible to automated retrieval specifically.

I have confirmed this from three different network environments — a commercial
cloud provider, a corporate network, and a residential connection — so it does
not appear to be limited to a particular address range or reputation class. The
same applies to the recent-communications export at
`/app/secure/ocl/lrs/do/rcntCmLgs`.

The reason I am raising it rather than simply working around it: these files are
published on the federal open-data portal under terms that contemplate
programmatic reuse, and the portal's own listings now point at URLs that no
automated consumer can retrieve. A challenge intended to deter scraping or
abusive traffic appears to be catching the routine open-data use case as well. I
suspect that was not the intent.

Two possible remedies, whichever suits your configuration:

1. **Exempt the open-data paths** from the bot challenge — the `/media/`
   resources referenced by the open.canada.ca records, at minimum. These are
   static published files, so exempting them should not weaken protection of the
   interactive registry application.
2. **Provide an alternative programmatic route** — a mirrored copy on
   open.canada.ca itself, loading the resources into the portal's DataStore, or
   a documented API endpoint. Any of these would be at least as robust for you
   as the current arrangement, since the catalogue records would no longer
   depend on a single host's WAF configuration.

I would be glad to re-test from any of those environments and confirm a fix, if
that is useful.

Thank you for your time.

[name]
[contact]

---

## Appendix — reproduction

```bash
curl -sS -o /dev/null -D - \
  "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
```

Observed response headers:

```
HTTP/2 403
cf-mitigated: challenge
server: cloudflare
cf-ray: <id>-YYZ
```

The same request from a browser session succeeds and returns the ZIP. The
challenge requires JavaScript execution, so no scripted HTTP client — including
ones that present a browser's TLS fingerprint — can complete it.

Affected paths:

| Path | Purpose |
|---|---|
| `/media/mqbbmaqk/communications_ocl_cal.zip` | Monthly Communication Reports bulk export |
| `/media/zwcjycef/registrations_enregistrements_ocl_cal.zip` | Lobbying Registrations bulk export |
| `/app/secure/ocl/lrs/do/rcntCmLgs` | Recent communications CSV export |
