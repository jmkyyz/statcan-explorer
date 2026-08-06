#!/usr/bin/env python3
"""Regenerate the provincial spending shares for tax-dollar-tracker.html.

Source: StatCan Table 10-10-0005-01, "Canadian Classification of Functions of
Government (CCOFOG) by consolidated government component", public sector
component 2 = "Consolidated provincial-territorial and local governments".

That component publishes all 60 CCOFOG members, so Transport [7045] and Public
debt transactions [7017] come out of the same table, same vintage, same
universe as the ten divisions. Table 10-10-0024-01's provincial-and-territorial
component publishes only the 10 divisions, which is why the earlier research
note concluded transport and debt were unobtainable.

The ten output categories are a partition of the ten CCOFOG divisions, so they
sum to the total by construction. Every claim the script relies on is asserted
below and the script fails loudly rather than emitting a quiet wrong number.

Usage:  python3 build_provincial_spending.py [--year 2024]
"""

import argparse
import json
import sys
import time
import urllib.request

PID = 10100005
COMPONENT = 2  # consolidated provincial-territorial and local governments
WDS = "https://www150.statcan.gc.ca/t1/wds/rest"

GEO = {2: "NL", 3: "PE", 4: "NS", 5: "NB", 6: "QC", 7: "ON", 8: "MB",
       9: "SK", 10: "AB", 11: "BC", 12: "YT", 13: "NT", 14: "NU"}

# CCOFOG memberId -> classification code, for the members this build needs.
DIVISION = {1: "701", 2: "702", 3: "703", 4: "704", 5: "705",
            6: "706", 7: "707", 8: "708", 9: "709", 10: "710"}
DEBT = 33      # 7017 Public debt transactions (child of 701)
TRANSPORT = 43  # 7045 Transport (child of 704)

# App category -> the CCOFOG arithmetic that produces it.
#   admin = 701 less the debt sub-function, i.e. general government administration
#   other = defence + recreation/culture/religion + economic affairs less transport
MAPPING = {
    "health":      lambda m: m[7],
    "socialEI":    lambda m: m[10],
    "debt":        lambda m: m[DEBT],
    "admin":       lambda m: m[1] - m[DEBT],
    "education":   lambda m: m[9],
    "transport":   lambda m: m[TRANSPORT],
    "justice":     lambda m: m[3],
    "housing":     lambda m: m[6],
    "environment": lambda m: m[5],
    "other":       lambda m: m[2] + m[8] + (m[4] - m[TRANSPORT]),
}
# Emission order matches the existing block in tax-dollar-tracker.html.
ORDER = ["health", "socialEI", "debt", "admin", "education",
         "transport", "justice", "housing", "environment", "other"]

NEEDED = sorted(set(DIVISION) | {DEBT, TRANSPORT})


def post(endpoint, payload):
    req = urllib.request.Request(
        f"{WDS}/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=120))


def fetch(year):
    """Return {(geoId, memberId): value} for the requested reference year.

    Responses are keyed off the coordinate each one carries. The WDS batch
    endpoint does not guarantee response order, so zipping against the request
    list silently scrambles the data.
    """
    reqs = [{"productId": PID,
             "coordinate": f"{g}.{COMPONENT}.{m}." + "0." * 6 + "0",
             "latestN": 12}
            for g in GEO for m in NEEDED]
    out, periods = {}, set()
    for i in range(0, len(reqs), 50):
        for r in post("getDataFromCubePidCoordAndLatestNPeriods", reqs[i:i + 50]):
            obj = r.get("object") or {}
            coord = obj.get("coordinate")
            if not coord:
                sys.exit(f"WDS returned no coordinate: {r.get('status')} {r}")
            parts = coord.split(".")
            g, m = int(parts[0]), int(parts[2])
            for dp in obj.get("vectorDataPoint") or []:
                periods.add(dp["refPer"][:4])
                if dp["refPer"][:4] == str(year):
                    out[(g, m)] = dp["value"]
        time.sleep(0.4)

    missing = [(GEO[g], m) for g in GEO for m in NEEDED if (g, m) not in out]
    if missing:
        sys.exit(f"reference year {year} missing for {len(missing)} cells "
                 f"(available: {min(periods)}-{max(periods)}): {missing[:8]}")
    return out


def shares(cells):
    result = {}
    for g, ab in GEO.items():
        m = {k: cells[(g, k)] for k in NEEDED}

        # The published hierarchy must hold, or the mapping is carving a
        # sub-function out of the wrong parent.
        assert m[DEBT] < m[1], f"{ab}: 7017 ({m[DEBT]}) >= 701 ({m[1]})"
        assert m[TRANSPORT] < m[4], f"{ab}: 7045 ({m[TRANSPORT]}) >= 704 ({m[4]})"

        amounts = {k: fn(m) for k, fn in MAPPING.items()}
        assert all(v >= 0 for v in amounts.values()), f"{ab}: negative category"

        # The ten categories partition the ten divisions exactly.
        total = sum(amounts.values())
        divisions = sum(m[d] for d in DIVISION)
        assert abs(total - divisions) < 1, f"{ab}: {total} != {divisions}"
        assert total > 0, f"{ab}: zero total"

        result[ab] = largest_remainder({k: 100 * amounts[k] / total for k in ORDER})
        result[ab]["_totalExpenditureM"] = total
    return result


def largest_remainder(exact):
    """Round to one decimal so the ten shares still sum to exactly 100.0.

    Rounding each share independently drifts by up to 0.5 points across ten
    categories, which is what forced the old block to be nudged to 100 by hand.
    """
    tenths = {k: v * 10 for k, v in exact.items()}
    floors = {k: int(v) for k, v in tenths.items()}
    short = 1000 - sum(floors.values())
    ranked = sorted(tenths, key=lambda k: tenths[k] - floors[k], reverse=True)
    for k in ranked[:short]:
        floors[k] += 1
    return {k: floors[k] / 10 for k in exact}


def emit(result, year):
    print(f"// Generated by build_provincial_spending.py — do not hand-edit.")
    print(f"// StatCan Table 10-10-0005-01, consolidated provincial-territorial")
    print(f"// and local governments, reference year {year}.")
    print(f"// Shares of total CCOFOG expenditure; each province sums to 100.0.")
    for ab in ORDER and sorted(result):
        row = result[ab]
        cells = ", ".join(f"{k}:{row[k]}" for k in ORDER)
        print(f"  {ab}: {{ {cells} }},  // total ${row['_totalExpenditureM']:,.0f}M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--json", help="also write the shares to this path")
    args = ap.parse_args()

    result = shares(fetch(args.year))
    emit(result, args.year)

    for ab, row in result.items():
        s = sum(row[k] for k in ORDER)
        if abs(s - 100.0) > 0.15:
            sys.exit(f"{ab}: rounded shares sum to {s}, not 100")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"source": "10-10-0005-01", "component":
                       "Consolidated provincial-territorial and local governments",
                       "referenceYear": args.year, "shares": result}, fh, indent=1)


if __name__ == "__main__":
    main()
