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

STATCAN_BASE = "https://www150.statcan.gc.ca/t1/wds/rest"

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
    n_periods = min(max(n_periods, 1), 1200)

    # ------------------------------------------------------------------
    # Step 1: Fetch data from StatCan
    # We use getDataFromVectorsAndLatestNPeriods.
    # If from/to are given we request enough periods to cover the range,
    # then filter client-side.
    # ------------------------------------------------------------------
    payload = [{"vectorId": int(v), "latestN": n_periods} for v in vector_ids]

    try:
        resp = requests.post(
            f"{STATCAN_BASE}/getDataFromVectorsAndLatestNPeriods",
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return jsonify({"error": "StatCan API timed out – try fewer periods or try again later"}), 504
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": f"StatCan API error: {exc}"}), 502

    raw = resp.json()

    # ------------------------------------------------------------------
    # Step 2: Resolve date boundaries
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
    # Step 3: Parse response into clean series objects
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
        scalar_code  = obj.get("scalarFactorCode", 0)
        multiplier   = SCALAR.get(scalar_code, 1)
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

            # Apply scalar multiplier
            try:
                value = float(raw_value) * multiplier
            except (TypeError, ValueError):
                continue

            label = period_label(ref_per, freq_code or 6)
            data_points.append({"label": label, "date": ref_per[:10], "value": value})

        results.append({
            "vectorId":  vector_id,
            "frequency": FREQ_LABEL.get(freq_code, "Unknown") if freq_code else "Unknown",
            "frequencyCode": freq_code,
            "scalarFactorCode": scalar_code,
            "multiplier": multiplier,
            "data": data_points,
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
