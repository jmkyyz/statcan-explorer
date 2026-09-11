# Access request — OCL open-data bulk files behind a bot challenge

**Status: ready to send.** The condition for sending is met — `check_sources.py`
confirmed on 2026-09-11 that neither bulk resource is DataStore-backed
(`datastore_active=False` on both), so there is no way to pull this data from
the open-data portal and no technical route left that does not involve either
the OCL or a browser.

**Send to:** `info@lobbycanada.gc.ca` — the `maintainer_email` published on both
affected dataset records, so it is the contact the Office itself nominates for
them.

If that gets no response, the most recently maintained OCL open-data record
(`b10e0c62-4a10-4670-bc8a-e4b842f2c89b`, May 2026) lists a named analyst as
maintainer, who likely administers the Office's open-data publishing directly.
Their address is in that record. Try `info@` first — going straight to a named
individual on a first contact tends to get forwarded back to the general inbox
anyway.

**Before sending, decide one thing:** the draft is written as an ordinary
open-data user. Adding an employer may get a faster reply, but it turns a bug
report into a media inquiry and will likely be routed to communications rather
than to whoever administers the WAF. The technical route is usually quicker.
Your call.

Keep the appendix. A report an administrator can reproduce in one command gets
fixed; one that cannot gets closed.

---

**Subject:** Open-data bulk files for the Registry of Lobbyists returning HTTP 403 to automated clients

Hello,

I want to flag what looks like an unintended side-effect of a recent change to
the lobbycanada.gc.ca web infrastructure.

The Office publishes two datasets on the Government of Canada's open-data
portal:

- **Lobbying Registrations**
  https://open.canada.ca/data/en/dataset/70ef2117-1095-4d77-80eb-b87f2bada2a4
- **Monthly Communication Reports**
  https://open.canada.ca/data/en/dataset/a34eb330-7136-4f5e-9f5f-3ba41df58b06

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

The reason I am raising it rather than simply working around it: the portal's
listings for these datasets point at URLs that no automated client can now
retrieve, and both records declare an update frequency of `P1W` — weekly. A
dataset published on a weekly cycle is one meant to be collected repeatedly
rather than fetched once by hand, and that is exactly the use the challenge now
blocks. I assume a rule aimed at scraping or abusive traffic has caught the
routine open-data case as a side-effect.

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
