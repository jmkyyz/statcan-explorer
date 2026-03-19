#!/usr/bin/env python3
"""
StatCan WDS Proxy Server
========================
Sits between your browser and the Statistics Canada WDS API, handling
CORS and translating raw WDS responses into a clean JSON format the
frontend can consume directly.

Usage:
    pip install flask flask-cors requests
    python proxy.py

The server will listen on http://localhost:5001
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow all origins (restrict in production)

# ---------------------------------------------------------------------------
# Route: GET /  →  serve the frontend
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(here, "statcan-explorer.html")

@app.route("/vectors-template.xlsx")
def vectors_template():
    here = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(here, "vectors-template.xlsx")

@app.route("/lab")
def lab():
    here = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(here, "statcan-explorer-lab.html")

STATCAN_BASE = "https://www150.statcan.gc.ca/t1/wds/rest"
BOC_BASE     = "https://www.bankofcanada.ca/valet"

# ---------------------------------------------------------------------------
# Scalar factor multipliers (from StatCan codeset)
# ---------------------------------------------------------------------------
SCALAR = {
    0: 1,           # units
    1: 10,
    2: 100,
    3: 1_000,
    4: 10_000,
    5: 100_000,
    6: 1_000_000,
    7: 10_000_000,
    8: 100_000_000,
    9: 1_000_000_000,
}

# ---------------------------------------------------------------------------
# Unit of Measure (UOM) codes from StatCan codeset.
# Each entry: (base_unit_label, multiplier_to_convert_to_base_unit)
# The multiplier is applied ON TOP of the scalar factor so that the frontend
# always receives values in the stated base unit (dollars, persons, etc.).
# ---------------------------------------------------------------------------
UOM_INFO = {
    0:   ("",                    1),
    9:   ("number",              1),
    14:  ("persons",         1_000),      # reported as thousands of persons
    17:  ("index",               1),      # index (e.g. CPI 2002=100)
    18:  ("percent",             1),
    20:  ("index",               1),
    21:  ("index",               1),
    39:  ("persons",             1),
    47:  ("hours",               1),
    48:  ("hours",               1),
    56:  ("dollars/hour",        1),
    81:  ("dollars",             1),
    115: ("",                1_000),      # generic thousands
    224: ("dollars",         1_000),      # thousands of dollars → dollars
    229: ("dollars",     1_000_000),      # millions of dollars  → dollars
    246: ("dollars", 1_000_000_000),      # billions of dollars  → dollars
    300: ("ppts",                1),
    301: ("percent",             1),
    428: ("persons",             1),      # persons (scalar handles scale)
}

# Frequency code -> human label
FREQ_LABEL = {
    1: "Daily",
    2: "Weekly",
    4: "Biweekly",
    6: "Monthly",
    9: "Quarterly",
    11: "Semi-annual",
    12: "Annual",
}

# ---------------------------------------------------------------------------
# Helper: convert a refPer date string + frequencyCode into a display label
# ---------------------------------------------------------------------------
def period_label(ref_per: str, freq_code: int) -> str:
    """
    StatCan returns refPer as YYYY-MM-DD always.
    We map it to a friendly label based on frequency:
      Monthly  -> "2023-01"
      Quarterly-> "2023 Q1"
      Annual   -> "2023"
    """
    try:
        d = datetime.strptime(ref_per[:10], "%Y-%m-%d")
    except ValueError:
        return ref_per

    if freq_code == 12:                    # Annual
        return str(d.year)
    if freq_code == 9:                     # Quarterly
        q = (d.month - 1) // 3 + 1
        return f"{d.year} Q{q}"
    if freq_code == 6:                     # Monthly
        return f"{d.year}-{d.month:02d}"
    if freq_code == 2:                     # Weekly
        return f"{d.year}-W{d.isocalendar()[1]:02d}"
    # Default: return ISO date
    return ref_per[:10]


# ---------------------------------------------------------------------------
# Route: GET /api/series
# Query params:
#   vectors  – comma-separated vector IDs, e.g. "41690973,2062809"
#   fromDate – ISO date string YYYY-MM-DD (preferred)
#   toDate   – ISO date string YYYY-MM-DD (preferred)
#   from     – start year fallback, e.g. "2010"
#   to       – end year fallback, e.g. "2024"
#   periods  – how many latest periods to request from StatCan (default 360)
# ---------------------------------------------------------------------------
@app.route("/api/series")
def get_series():
    raw_vectors   = request.args.get("vectors",  "")
    from_date_str = request.args.get("fromDate", "")
    to_date_str   = request.args.get("toDate",   "")
    from_year     = request.args.get("from",     type=int)
    to_year       = request.args.get("to",       type=int)
    n_periods     = request.args.get("periods",  default=360, type=int)

    if not raw_vectors:
        return jsonify({"error": "No vectors specified"}), 400

    vector_ids = [v.strip().lstrip("vV") for v in raw_vectors.split(",") if v.strip()]
    if not vector_ids:
        return jsonify({"error": "No valid vector IDs"}), 400

    # Clamp n_periods to something reasonable
    # Daily series can require up to 3650+ periods for a 10-year range
    n_periods = min(max(n_periods, 1), 4000)

    # ------------------------------------------------------------------
    # Steps 1+2: Fire both StatCan requests in parallel.
    #   • getSeriesInfoFromVector     → memberUomCode + scalarFactorCode
    #   • getDataFromVectorsAndLatestNPeriods → actual data points
    # The data endpoint returns scalarFactorCode=None at the series level
    # (it lives per data-point there), so we must rely on the info endpoint.
    # ------------------------------------------------------------------
    info_payload = [{"vectorId": int(v)} for v in vector_ids]
    data_payload = [{"vectorId": int(v), "latestN": n_periods} for v in vector_ids]

    info_result = {}   # will hold the raw JSON from getSeriesInfoFromVector
    data_result = {}   # will hold the raw JSON from getDataFromVectorsAndLatestNPeriods
    data_error  = None

    def _fetch_info():
        r = requests.post(
            f"{STATCAN_BASE}/getSeriesInfoFromVector",
            json=info_payload, timeout=25,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def _fetch_data():
        r = requests.post(
            f"{STATCAN_BASE}/getDataFromVectorsAndLatestNPeriods",
            json=data_payload, timeout=35,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_info = pool.submit(_fetch_info)
        fut_data = pool.submit(_fetch_data)
        # Data fetch is mandatory; info fetch is best-effort
        try:
            data_result = fut_data.result()
        except requests.exceptions.Timeout:
            return jsonify({"error": "StatCan API timed out – try fewer periods or try again later"}), 504
        except requests.exceptions.RequestException as exc:
            return jsonify({"error": f"StatCan API error: {exc}"}), 502
        try:
            info_result = fut_info.result()
        except Exception:
            info_result = []   # fallback: no UOM conversion

    # Build lookup dicts from series info
    uom_by_vector: dict[int, int] = {}
    scalar_by_vector: dict[int, int] = {}
    for info_item in (info_result or []):
        if info_item.get("status") == "SUCCESS":
            io = info_item["object"]
            vid = io.get("vectorId")
            if vid is not None:
                uom_by_vector[int(vid)]    = int(io.get("memberUomCode",    0) or 0)
                scalar_by_vector[int(vid)] = int(io.get("scalarFactorCode", 0) or 0)

    raw = data_result

    # ------------------------------------------------------------------
    # Step 3: Resolve date boundaries
    # ------------------------------------------------------------------
    start_date = None
    end_date   = None

    if from_date_str:
        try:
            start_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    elif from_year:
        start_date = date(from_year, 1, 1)

    if to_date_str:
        try:
            end_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    elif to_year:
        end_date = date(to_year, 12, 31)

    # ------------------------------------------------------------------
    # Step 4: Parse response into clean series objects
    # ------------------------------------------------------------------
    results = []

    for item in raw:
        if item.get("status") != "SUCCESS":
            results.append({
                "vectorId": None,
                "error": item.get("object", "Unknown error from StatCan"),
            })
            continue

        obj = item["object"]
        vector_id    = obj.get("vectorId")
        freq_code    = None

        # Use scalarFactorCode and memberUomCode from the pre-fetched series
        # info (getSeriesInfoFromVector).  The data endpoint returns
        # scalarFactorCode = None at the series level (it's per data-point
        # there), so we must rely on the info endpoint for correctness.
        vid_int      = int(vector_id) if vector_id is not None else None
        scalar_code  = scalar_by_vector.get(vid_int, 0) if vid_int else 0
        multiplier   = SCALAR.get(scalar_code, 1)

        uom_code     = uom_by_vector.get(vid_int, 0) if vid_int else 0
        uom_label, uom_mult = UOM_INFO.get(uom_code, ("", 1))
        total_mult   = multiplier * uom_mult   # scalar × UOM conversion

        data_points  = []

        for dp in obj.get("vectorDataPoint", []):
            ref_per   = dp.get("refPer", "")
            raw_value = dp.get("value")
            freq_code = dp.get("frequencyCode", freq_code)

            # Skip suppressed / unavailable data points
            if raw_value is None or dp.get("statusCode") in (1, 8, 9):
                continue

            # Date range filter
            if start_date or end_date:
                try:
                    dp_date = datetime.strptime(ref_per[:10], "%Y-%m-%d").date()
                    if start_date and dp_date < start_date:
                        continue
                    if end_date and dp_date > end_date:
                        continue
                except ValueError:
                    pass

            # Apply scalar × UOM multiplier to convert to base unit
            try:
                value = float(raw_value) * total_mult
            except (TypeError, ValueError):
                continue

            label = period_label(ref_per, freq_code or 6)
            data_points.append({"label": label, "date": ref_per[:10], "value": value})

        results.append({
            "vectorId":        vector_id,
            "frequency":       FREQ_LABEL.get(freq_code, "Unknown") if freq_code else "Unknown",
            "frequencyCode":   freq_code,
            "scalarFactorCode": scalar_code,
            "uomCode":         uom_code,
            "uom":             uom_label,   # base unit after conversion (e.g. "dollars")
            "multiplier":      total_mult,  # scalar × UOM multiplier actually applied
            "data":            data_points,
        })

    return jsonify({"series": results})


# ---------------------------------------------------------------------------
# Route: GET /api/metadata
# Query params:
#   vectors – comma-separated vector IDs
# ---------------------------------------------------------------------------
@app.route("/api/metadata")
def get_metadata():
    raw_vectors = request.args.get("vectors", "")
    if not raw_vectors:
        return jsonify({"error": "No vectors specified"}), 400

    vector_ids = [v.strip().lstrip("vV") for v in raw_vectors.split(",") if v.strip()]
    payload = [{"vectorId": int(v)} for v in vector_ids]

    try:
        resp = requests.post(
            f"{STATCAN_BASE}/getSeriesInfoFromVector",
            json=payload,
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": f"StatCan API error: {exc}"}), 502

    raw = resp.json()
    results = []
    for item in raw:
        if item.get("status") != "SUCCESS":
            results.append({"error": item.get("object", "Error")})
            continue
        obj = item["object"]
        results.append({
            "vectorId":     obj.get("vectorId"),
            "productId":    obj.get("productId"),
            "coordinate":   obj.get("coordinate"),
            "titleEn":      obj.get("SeriesTitleEn", ""),
            "titleFr":      obj.get("SeriesTitleFr", ""),
            "frequencyCode": obj.get("frequencyCode"),
            "frequency":    FREQ_LABEL.get(obj.get("frequencyCode"), "Unknown"),
            "scalarFactorCode": obj.get("scalarFactorCode", 0),
            "terminated":   obj.get("terminated", 0),
        })

    return jsonify({"metadata": results})


# ---------------------------------------------------------------------------
# Route: GET /api/table-metadata
# Query params:
#   pid – product/table ID, e.g. "36100104"  (digits only, no dashes)
# ---------------------------------------------------------------------------
@app.route("/api/table-metadata")
def get_table_metadata():
    pid_raw = request.args.get("pid", "")
    if not pid_raw:
        return jsonify({"error": "No pid specified"}), 400

    pid = re.sub(r"\D", "", pid_raw)   # strip dashes/spaces
    payload = [{"productId": int(pid)}]

    try:
        resp = requests.post(
            f"{STATCAN_BASE}/getCubeMetadata",
            json=payload,
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": f"StatCan API error: {exc}"}), 502

    raw = resp.json()
    if not raw or raw[0].get("status") != "SUCCESS":
        return jsonify({"error": "Table not found or StatCan error"}), 404

    obj = raw[0]["object"]
    return jsonify({
        "productId":    obj.get("productId"),
        "cansimId":     obj.get("cansimId"),
        "titleEn":      obj.get("cubeTitleEn"),
        "titleFr":      obj.get("cubeTitleFr"),
        "startDate":    obj.get("cubeStartDate"),
        "endDate":      obj.get("cubeEndDate"),
        "frequency":    FREQ_LABEL.get(obj.get("frequencyCode"), "Unknown"),
        "frequencyCode": obj.get("frequencyCode"),
        "releaseTime":  obj.get("releaseTime"),
        "dimensions":   obj.get("dimension", []),
    })


# ---------------------------------------------------------------------------
# Route: GET /api/boc
# Query params:
#   series   – comma-separated BoC V-codes, e.g. "V39079,V39078"
#   fromDate – ISO date string YYYY-MM-DD
#   toDate   – ISO date string YYYY-MM-DD
#
# Fetches from the Bank of Canada Valet API and converts daily observations
# to monthly (last value per calendar month) so the frontend treats BoC
# series identically to StatCan monthly series.
# ---------------------------------------------------------------------------
@app.route("/api/boc")
def get_boc_series():
    raw_series = request.args.get("series",   "")
    from_date  = request.args.get("fromDate", "")
    to_date    = request.args.get("toDate",   "")

    if not raw_series:
        return jsonify({"error": "No series specified"}), 400

    series_codes = [s.strip() for s in raw_series.split(",") if s.strip()]
    results = []

    for code in series_codes:
        # The frontend strips a leading v/V via replace(/^[vV]/, ''), turning
        # "V39079" → "39079".  Re-add the prefix only for pure numeric codes.
        # Named codes (FXUSDCAD, BD.CDN.10YR.DQ.YLD, W.BCPI, etc.) are passed
        # through unchanged because they contain non-digit characters.
        boc_code = f"V{code}" if code.isdigit() else code

        params = {}
        if from_date:
            params["start_date"] = from_date
        if to_date:
            params["end_date"] = to_date

        try:
            resp = requests.get(
                f"{BOC_BASE}/observations/{boc_code}/json",
                params=params,
                timeout=25,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            results.append({"vectorId": code, "error": str(exc)})
            continue

        data         = resp.json()
        observations = data.get("observations", [])

        # Convert to monthly: keep the last daily value for each calendar month
        monthly = {}   # "YYYY-MM" → {"date": "YYYY-MM-DD", "value": float}
        for obs in observations:
            d = obs.get("d", "")
            if not d:
                continue
            val_obj = obs.get(boc_code, {})   # BoC payload key uses V-prefix
            val = val_obj.get("v")
            if val is None or val == "":
                continue
            try:
                val_f = float(val)
            except (ValueError, TypeError):
                continue
            month_key = d[:7]                           # "YYYY-MM"
            # Later dates overwrite earlier ones → end-of-month wins
            if month_key not in monthly or d > monthly[month_key]["date"]:
                monthly[month_key] = {"date": d, "value": val_f}

        data_points = [
            {"label": mk, "date": monthly[mk]["date"], "value": monthly[mk]["value"]}
            for mk in sorted(monthly)
        ]

        results.append({
            "vectorId":      code,
            "frequency":     "Monthly",
            "frequencyCode": 6,
            "uom":           "percent",
            "data":          data_points,
        })

    return jsonify({"series": results})


# ---------------------------------------------------------------------------
# Route: GET /api/health
# ---------------------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "statcan_base": STATCAN_BASE})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("=" * 60)
    print(f"  StatCan WDS Proxy  →  http://localhost:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
