#!/usr/bin/env python3
"""CIMT Trade Explorer — publish a trimmed slice to Cloudflare R2 (Phase 5).

The full 20-year, HS10-detail store stays local. For the always-on online copy
(coworkers, no local data) we publish a much smaller slice — the last N years at
the HS2/HS4/HS6 rollup tiers only — to Cloudflare R2 object storage. Smaller =
faster remote queries; storage is pennies either way. The app prefers a full
local store and falls back to this slice when there isn't one.

Two steps:
  python publish.py --stage             # build data/publish/parquet locally
  python publish.py --upload            # sync it to R2 (needs creds, see below)
  python publish.py --stage --upload    # both

What's included: tiers hs2/hs4/hs6 for year >= (latest - YEARS + 1), plus the
dimension lookups. Excluded: the hs8/HS10 detail tiers (local-only).

R2 credentials (env vars, S3-compatible — create a bucket + API token in the
Cloudflare dashboard first):
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
  R2_PREFIX (optional, default "cimt")
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARQUET = HERE / "data" / "parquet"
PUBLISH = HERE / "data" / "publish" / "parquet"

ONLINE_TIERS = ["hs2", "hs4", "hs6"]   # HS6 is the deepest online level
DEFAULT_YEARS = 10


def latest_year() -> int:
    years = []
    for d in (PARQUET / "hs6").glob("flow=*/year=*"):
        try:
            years.append(int(d.name.split("=")[1]))
        except (IndexError, ValueError):
            pass
    if not years:
        sys.exit(f"no data under {PARQUET/'hs6'} — run ingest first")
    return max(years)


def stage(years: int) -> None:
    cutoff = latest_year() - years + 1
    if PUBLISH.exists():
        shutil.rmtree(PUBLISH)
    PUBLISH.mkdir(parents=True)
    kept = 0
    for tier in ONLINE_TIERS:
        for ydir in (PARQUET / tier).glob("flow=*/year=*"):
            yr = int(ydir.name.split("=")[1])
            if yr < cutoff:
                continue
            dest = PUBLISH / tier / ydir.parent.name / ydir.name
            dest.mkdir(parents=True, exist_ok=True)
            for f in ydir.glob("*.parquet"):
                shutil.copy2(f, dest / f.name)
                kept += 1
    # dimension lookups (small; needed for labels)
    if (PARQUET / "dim").exists():
        shutil.copytree(PARQUET / "dim", PUBLISH / "dim")
    write_manifest()
    size = sum(f.stat().st_size for f in PUBLISH.rglob("*") if f.is_file())
    print(f"staged {kept} partition files, years {cutoff}+, tiers "
          f"{'/'.join(ONLINE_TIERS)} -> {PUBLISH}")
    print(f"slice size: {size/1e9:.2f} GB")


def write_manifest() -> None:
    """Browser data-layer needs an explicit file index — object storage has no
    directory listing, so DuckDB-WASM can't glob. Records tiers/flows/years and
    the period range so the client can build read_parquet([...]) file lists."""
    import duckdb
    con = duckdb.connect()
    src = (f"read_parquet('{(PUBLISH/'hs6').as_posix()}/**/*.parquet', "
           f"hive_partitioning=true)")
    pmin, pmax = con.execute(
        f"SELECT min(year*100+month), max(year*100+month) FROM {src}").fetchone()
    rows = con.execute(
        f"SELECT DISTINCT flow, year FROM {src} ORDER BY flow, year").fetchall()
    flows = sorted({r[0] for r in rows})
    years = sorted({r[1] for r in rows})
    dims = sorted(p.stem for p in (PUBLISH / "dim").glob("*.parquet"))
    manifest = {
        "tiers": ONLINE_TIERS,
        "flows": flows,
        "years": years,
        "period_min": pmin,
        "period_max": pmax,
        "dims": dims,
        "detail": False,            # online slice has no HS8/HS10 detail
    }
    (PUBLISH / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {len(flows)} flows, years {years[0]}–{years[-1]}, "
          f"period {pmin}–{pmax}")


def upload(prefix: str) -> None:
    try:
        import boto3
    except ImportError:
        sys.exit("pip install boto3 to upload to R2")
    need = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        sys.exit(f"missing R2 env vars: {missing}")
    if not PUBLISH.exists():
        sys.exit("nothing staged — run with --stage first")
    # Tolerate R2_ACCOUNT_ID being pasted as the full endpoint URL — pull the
    # 32-hex account id out of whatever was provided.
    acct = os.environ["R2_ACCOUNT_ID"].strip()
    m = re.search(r"[0-9a-fA-F]{32}", acct)
    acct = m.group(0) if m else acct
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]
    n = 0
    for f in PUBLISH.rglob("*"):
        if not f.is_file():
            continue
        key = f"{prefix}/{f.relative_to(PUBLISH).as_posix()}"
        s3.upload_file(str(f), bucket, key)
        n += 1
    print(f"uploaded {n} files to r2://{bucket}/{prefix}/")


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish trimmed CIMT slice to R2")
    ap.add_argument("--stage", action="store_true", help="build the slice locally")
    ap.add_argument("--upload", action="store_true", help="sync the slice to R2")
    ap.add_argument("--years", type=int, default=DEFAULT_YEARS,
                    help=f"years of history to include (default {DEFAULT_YEARS})")
    args = ap.parse_args()
    if not (args.stage or args.upload):
        ap.error("pass --stage and/or --upload")
    if args.stage:
        stage(args.years)
    if args.upload:
        upload(os.environ.get("R2_PREFIX", "cimt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
