#!/usr/bin/env python3
"""
Source reachability probe for the lobbyist pipeline.

Answers the two open questions from the 2026-07 outage in one run, from
whatever machine you run it on:

  A. Does lobbycanada.gc.ca still serve us, or are we challenged?
     The block that killed the pipeline is IP-reputation-based: GitHub-hosted
     runners have been 403'd since 2026-07-20, and a colleague's fork on his
     employer's servers hits a Cloudflare interstitial — but the Mac published
     fine from a residential IP on 2026-07-21 and has not been tested since.
     RUN THIS FROM THE MAC to settle it.

  B. Is the same data on open.canada.ca's CKAN portal, and is it actually
     downloadable from there?
     A CKAN dataset only helps if its resource URLs point at portal storage.
     If they point back at lobbycanada.gc.ca, the download walks into the same
     wall and only change-detection improves.

Read-only: issues HEAD-ish streamed GETs and catalogue queries, downloads no
bulk data, writes nothing.

    python3 check_sources.py            # both probes
    python3 check_sources.py --registry # part A only
    python3 check_sources.py --ckan     # part B only
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BULK = {
    "communications (bulk ZIP)":
        "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip",
    "registrations (bulk ZIP)":
        "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip",
}
# The live endpoint patch_recent.py tops up from — a search app, not a dataset,
# so CKAN will not replace it. Worth knowing separately whether it still answers.
LIVE_URL = "https://lobbycanada.gc.ca/app/secure/ocl/lrs/do/rcntCmLgs"

CKAN = "https://open.canada.ca/data/en/api/3/action"
CKAN_QUERIES = ["lobbyist", "lobbying", "registry of lobbyists",
                "commissioner of lobbying"]
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Cloudflare leaves these behind on a challenge; they distinguish "blocked by
# bot management" from "server is just unhappy".
CF_HEADERS = ("cf-mitigated", "cf-ray", "cf-chl-bypass", "server")


def _cf_note(headers) -> str:
    bits = []
    for h in CF_HEADERS:
        v = headers.get(h)
        if v:
            bits.append(f"{h}={v}")
    return "  [" + ", ".join(bits) + "]" if bits else ""


def probe_registry() -> dict:
    """Part A — can this machine still fetch from lobbycanada.gc.ca?"""
    print("=" * 72)
    print("A. lobbycanada.gc.ca  (run this from the Mac to test a residential IP)")
    print("=" * 72)
    try:
        from curl_cffi import requests
    except ImportError:
        print("  curl_cffi is not installed — it is what production uses to get")
        print("  past JA3/TLS fingerprinting, so a plain-client result would not")
        print("  be comparable. Install it and re-run:  pip install curl_cffi")
        print("  (note: it is imported by build_db.py and patch_recent.py but is")
        print("   missing from lobbyist/requirements.txt)")
        return {"ok": None, "reason": "curl_cffi missing"}

    results = {}
    targets = list(BULK.items()) + [("recent-comms (live endpoint)", LIVE_URL)]
    for label, url in targets:
        params = ({"dateType": "4", "fromDate": "2026-09-01",
                   "toDate": "2026-09-07", "csv": ""}
                  if url == LIVE_URL else None)
        try:
            r = requests.get(url, params=params, impersonate="chrome",
                             stream=True, timeout=30)
            code = r.status_code
            size = r.headers.get("Content-Length", "?")
            lm = r.headers.get("Last-Modified", "—")
            note = _cf_note(r.headers)
            r.close()
            ok = code == 200
            results[label] = ok
            flag = "OK  " if ok else "FAIL"
            print(f"  [{flag}] {label}")
            print(f"         HTTP {code}   bytes={size}   Last-Modified={lm}{note}")
            if code == 403:
                print("         -> 403 is the signature of the block. A cf-mitigated")
                print("            header means a managed challenge: no TLS-impersonating")
                print("            client can clear it, only a real browser.")
        except Exception as e:            # noqa: BLE001 — report, never raise
            results[label] = False
            print(f"  [FAIL] {label}\n         {type(e).__name__}: {e}")
    return {"ok": all(results.values()) if results else False, "detail": results}


CKAN_HEADERS = {
    "User-Agent": BROWSER_UA,                    # the GC WAF rejects python-urllib
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
}


def _ckan(action: str, **params):
    """Query the CKAN API, preferring curl_cffi over stdlib urllib.

    urllib validates against Python's own CA bundle, which on a python.org
    macOS build is empty until `Install Certificates.command` has been run —
    that surfaces as CERTIFICATE_VERIFY_FAILED / "self-signed certificate in
    certificate chain" and looks exactly like the catalogue being down. Any
    TLS-inspecting proxy produces the same error. curl_cffi carries its own
    trust store, so if it is installed (it is a production dependency here)
    it sidesteps the whole question.
    """
    url = f"{CKAN}/{action}?" + urllib.parse.urlencode(params)
    try:
        from curl_cffi import requests as cc
    except ImportError:
        cc = None
    if cc is not None:
        r = cc.get(url, headers=CKAN_HEADERS, impersonate="chrome", timeout=30)
        r.raise_for_status()
        return r.json().get("result")
    req = urllib.request.Request(url, headers=CKAN_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("result")


def probe_ckan() -> dict:
    """Part B — is the registry published on open.canada.ca, and downloadable?"""
    print()
    print("=" * 72)
    print("B. open.canada.ca CKAN catalogue")
    print("=" * 72)

    found = {}
    errors = 0
    for q in CKAN_QUERIES:
        try:
            res = _ckan("package_search", q=q, rows=10)
        except Exception as e:            # noqa: BLE001
            errors += 1
            print(f"  query {q!r} failed: {type(e).__name__}: {e}")
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                print("    ^ a local TLS trust problem, NOT the catalogue being down.")
                print("      Fix: run  /Applications/Python\\ 3.x/Install\\ Certificates.command")
                print("      or:   pip install curl_cffi   (this script prefers it)")
            continue
        for pkg in (res or {}).get("results", []):
            found.setdefault(pkg.get("name"), pkg)

    if not found:
        # "every query errored" is NOT "the catalogue has nothing" — conflating
        # the two is the exact failure that hid this outage for seven weeks.
        if errors == len(CKAN_QUERIES):
            print("  Could not reach the catalogue at all — this says nothing")
            print("  about whether the dataset exists. Check your network and retry.")
            return {"datasets": 0, "portal_hosted": 0, "unreachable": True}
        print("  No matching datasets. Try browsing:")
        print("  https://open.canada.ca/data/en/dataset?q=lobbyist")
        return {"datasets": 0, "portal_hosted": 0, "unreachable": False}

    if errors:
        print(f"  ({errors} of {len(CKAN_QUERIES)} queries failed — results may be partial)")
    print(f"  {len(found)} candidate dataset(s) — most are keyword noise;")
    print(f"  what matters is where the two bulk ZIPs resolve.\n")
    targets = []
    portal_hosted = 0
    for name, pkg in found.items():
        title = (pkg.get("title") or "")
        if isinstance(title, dict):                     # GC returns bilingual dicts
            title = title.get("en", "")
        org = (pkg.get("organization") or {}).get("title", "")
        if isinstance(org, dict):
            org = org.get("en", "")
        print(f"  • {title}")
        print(f"    name={name}")
        print(f"    org={org}")
        # The update-frequency field is the answer to "how often is this refreshed"
        for key in ("frequency", "update_frequency", "maintenance_and_update_frequency"):
            if pkg.get(key):
                print(f"    {key}={pkg[key]}")
        print(f"    metadata_modified={pkg.get('metadata_modified')}")

        for r in pkg.get("resources", []):
            url = r.get("url", "")
            host = urllib.parse.urlparse(url).netloc
            # Only the bulk ZIPs the pipeline actually reads count. A keyword
            # search drags in briefing PDFs, other jurisdictions' registers and
            # unrelated "registry" datasets; counting those as a bypass would
            # be a false positive dressed up as a verdict.
            is_target = any(url.split("?")[0] == t.split("?")[0]
                            for t in BULK.values())
            if is_target:
                targets.append((title, url, host, pkg.get("frequency", "?")))
            if "lobbycanada.gc.ca" in host:
                verdict = "<< points back at lobbycanada — same wall"
            elif host:
                verdict = "<< portal-hosted, bypasses the wall"
                portal_hosted += 1
            else:
                verdict = ""
            if is_target:
                verdict += "   *** THIS IS A BULK SOURCE THE PIPELINE USES ***"
            print(f"      - {r.get('format','?'):<6} {host or '(no url)'} {verdict}")
            print(f"        last_modified={r.get('last_modified') or r.get('created')}"
                  f"  size={r.get('size')}")
            print(f"        {url}")
        print()
    print("  " + "-" * 68)
    if targets:
        print("  BULK SOURCES THE PIPELINE READS:")
        for title, url, host, freq in targets:
            state = ("BLOCKED (lobbycanada)" if "lobbycanada.gc.ca" in host
                     else f"portal-hosted ({host})")
            print(f"    {state}  declared update frequency={freq}")
            print(f"      {title}\n      {url}")
    else:
        print("  Neither bulk ZIP appears as a catalogue resource.")
    return {"datasets": len(found), "portal_hosted": portal_hosted,
            "unreachable": False, "targets": targets,
            "targets_usable": [t for t in targets
                               if "lobbycanada.gc.ca" not in t[2]]}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", action="store_true", help="part A only")
    ap.add_argument("--ckan", action="store_true", help="part B only")
    args = ap.parse_args()
    both = not (args.registry or args.ckan)

    reg = probe_registry() if (both or args.registry) else None
    ckan = probe_ckan() if (both or args.ckan) else None

    print("=" * 72)
    print("VERDICT")
    print("=" * 72)
    if reg is not None:
        if reg["ok"] is None:
            print("  A. inconclusive — install curl_cffi and re-run.")
        elif reg["ok"]:
            print("  A. This IP still reaches the registry. A self-hosted runner on")
            print("     this machine restores the pipeline with no rearchitecting —")
            print("     the quick fix is back on the table.")
        else:
            print("  A. This IP is blocked too. Relocating the job cannot fix it;")
            print("     you need a different source (B) or a real browser.")
    if ckan is not None:
        if ckan.get("targets_usable"):
            print(f"  B. {len(ckan['targets_usable'])} bulk source(s) are portal-hosted —")
            print("     a Cloudflare-free path to the data. Worth switching to.")
        elif ckan.get("targets"):
            print("  B. The catalogue lists the bulk data but every resource URL")
            print("     points back at lobbycanada.gc.ca — the same wall. CKAN")
            print("     does NOT give you a download path; it only confirms the")
            print("     dataset is still published and how often it should update.")
            print(f"     ({ckan['portal_hosted']} other portal-hosted resources were")
            print("     found, but they belong to unrelated datasets.)")
        elif ckan["datasets"]:
            print("  B. Datasets exist but resources link back to lobbycanada.gc.ca.")
            print("     Useful for change detection, not for the download itself.")
        elif ckan.get("unreachable"):
            print("  B. INCONCLUSIVE — the catalogue was unreachable from here.")
            print("     This is not evidence that the dataset does not exist.")
        else:
            print("  B. Nothing found in the catalogue.")
    print()
    print("  Either way, patch_recent.py's live endpoint is a search app, not a")
    print("  dataset — CKAN will not replace it. If A fails and B succeeds, the")
    print("  bulk rebuild is fixed and the daily top-up still needs an answer.")


if __name__ == "__main__":
    sys.exit(main())
