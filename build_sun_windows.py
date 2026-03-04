#!/usr/bin/env python3
"""
build_sun_windows.py
====================

Purpose
-------
Maintain a small JSON file with Sun-event timestamps needed by the imaging gate.

This script computes Sun events (geometric/civil/nautical/astronomical) for
three UTC dates:

- yesterday (UTC)
- today (UTC)
- tomorrow (UTC)

and stores them in a compact JSON file. The imaging gate (`sun_gate.py`) can
then decide whether it is currently "dark" by reading this file once and
selecting the relevant events (possibly needing the day before/after depending
on where 'now' falls relative to twilight times).

This script is designed to be run frequently (e.g. every minute via cron), but
it will only do the expensive work (GPS acquisition + Astral calculations) when
the output JSON is missing or "stale" (older than a configured number of hours).

User override
-------------
By default, latitude/longitude are obtained via the existing FetchGPS module.
Optionally, the user can pass --lat/--lon to bypass GPS fetching entirely
(useful if GPS is unavailable or unreliable).

Design notes
------------
- Astral runs fully offline (no internet required).
- GPS acquisition is done via the existing FetchGPS module, which performs GPS
  polling at import time. We therefore avoid importing it unless we actually
  need to rebuild the JSON.
- When using GPS, we only update the JSON when GPSMode == 3 (3D fix). If GPS is
  not locked, we do not overwrite the file.

Dependencies
------------
- Astral (offline): `python3 -m pip install --user astral`
- Existing GPS acquisition module:
    /home/pi/Tools/FetchGPS/FetchGPS.py
  NOTE: FetchGPS performs GPS acquisition at import time.

File locations
--------------
IMPORTANT: Do NOT write under /home/pi/Tools/Status/ because gonet4.py wipes it.

- Output JSON:
    /home/pi/Tools/Sun/sun_windows.json

- Log:
    /home/pi/Tools/Sun/sun_update.log

Typical cron entry (with a lock to avoid overlap)
-------------------------------------------------
* * * * * flock -n /tmp/gonet_sun_update.lock /usr/bin/python3 /home/pi/Tools/Crontab/build_sun_windows.py

Examples
--------
# Normal mode (use GPS if a rebuild is needed)
python3 /home/pi/Tools/Crontab/build_sun_windows.py

# Override GPS (bypass FetchGPS entirely)
python3 /home/pi/Tools/Crontab/build_sun_windows.py --lat 41.8781 --lon -87.6298

"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astral import LocationInfo
from astral.sun import sun, dawn, dusk


# -----------------------------------------------------------------------------
# USER SETTINGS (simple constants near the top)
# -----------------------------------------------------------------------------

# Where FetchGPS lives (this module acquires a GPS fix at import time).
FETCHGPS_PATH = "/home/pi/Tools/FetchGPS"

# Output directory (NOT wiped by gonet4.py)
#OUT_DIR = Path("/home/pi/Tools/Sun")
OUT_DIR = Path(".")  # temporary path for testing; change back to /home/pi/Tools/Sun in production
OUT_JSON = OUT_DIR / "sun_windows.json"
OUT_LOG = OUT_DIR / "sun_update.log"

# Recompute only if the JSON file is missing OR older than this many hours.
STALE_AFTER_HOURS = 12

# Use UTC everywhere to avoid DST/local-time ambiguity.
TZ = timezone.utc


# -----------------------------------------------------------------------------
# Main (keep linear: minimal helper functions, easy to read)
# -----------------------------------------------------------------------------

def main() -> int:
    """
    Build/update the sun window JSON if it is missing or stale.

    Returns
    -------
    int
        Always returns 0 so cron doesn't treat failures as fatal.
    """
    # -------------------------------------------------------------------------
    # 0) Parse optional user-provided GPS override
    # -------------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Build/update a 3-day (yesterday/today/tomorrow UTC) twilight table for the imaging gate."
    )
    parser.add_argument("--lat", type=float, default=None, help="Override latitude (decimal degrees).")
    parser.add_argument("--lon", type=float, default=None, help="Override longitude (decimal degrees).")
    args = parser.parse_args()

    override_mode = (args.lat is not None) or (args.lon is not None)
    if override_mode and (args.lat is None or args.lon is None):
        # Keep behavior explicit: if overriding, require both lat and lon.
        print("If providing a GPS override, you must provide both --lat and --lon.")
        return 0

    # Ensure output directory exists
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1) Decide whether we actually need to do work (fast path)
    # -------------------------------------------------------------------------
    now_utc = datetime.now(TZ)

    # If the JSON exists and is fresh, exit immediately (no GPS work).
    if OUT_JSON.exists():
        mtime = datetime.fromtimestamp(OUT_JSON.stat().st_mtime, TZ)
        age = now_utc - mtime
        if age < timedelta(hours=STALE_AFTER_HOURS):
            return 0

    # -------------------------------------------------------------------------
    # 2) Determine coordinates
    #    - If user provided --lat/--lon, bypass FetchGPS
    #    - Otherwise, attempt GPS acquisition (expensive: FetchGPS runs on import)
    # -------------------------------------------------------------------------
    gps_mode = 0
    latitude = 0.0
    longitude = 0.0

    if override_mode:
        latitude = float(args.lat)
        longitude = float(args.lon)
        gps_mode = 999  # sentinel meaning "user override"
    else:
        # Make FetchGPS importable
        if FETCHGPS_PATH not in sys.path:
            sys.path.insert(0, FETCHGPS_PATH)

        try:
            import FetchGPS  # type: ignore
        except Exception as e:
            with OUT_LOG.open("a") as f:
                f.write(f"{now_utc.isoformat().replace('+00:00','Z')} ERROR importing FetchGPS: {e!r}\n")
            return 0

        # Read GPS values produced by FetchGPS
        # FetchGPS sets GPSMode == 3 when it achieves a 3D fix (and breaks early).
        gps_mode = int(getattr(FetchGPS, "GPSMode", 0))
        latitude = float(getattr(FetchGPS, "GPSLat", 0.0))
        longitude = float(getattr(FetchGPS, "GPSLong", 0.0))

        # Only update the table if we have a 3D GPS fix.
        # If we don't, we fail gracefully and keep any existing JSON (or none).
        if gps_mode != 3:
            with OUT_LOG.open("a") as f:
                f.write(
                    f"{now_utc.isoformat().replace('+00:00','Z')} "
                    f"GPSMode={gps_mode} (no 3D fix). Not updating {OUT_JSON}\n"
                )
            return 0

    # -------------------------------------------------------------------------
    # 3) Compute twilight event times for yesterday/today/tomorrow (UTC)
    # -------------------------------------------------------------------------
    # Astral works fully offline; it uses only lat/lon/date/time inputs.
    loc = LocationInfo(
        name="GONet",
        region="site",
        timezone="UTC",
        latitude=latitude,
        longitude=longitude,
    )

    # We compute events for three dates so the gate can easily handle cases where
    # twilight times straddle the UTC date boundary.
    d_y = (now_utc - timedelta(days=1)).date()
    d_t = now_utc.date()
    d_n = (now_utc + timedelta(days=1)).date()

    # Convert Astral datetimes to UTC with no microseconds for stable JSON output.
    def _to_utc(dt: datetime) -> datetime:
        return dt.astimezone(TZ).replace(microsecond=0)

    # twilights is a list of 3 dicts in this fixed order:
    #   twilights[0] -> yesterday (UTC)
    #   twilights[1] -> today (UTC)
    #   twilights[2] -> tomorrow (UTC)
    twilights: list[dict] = [{}, {}, {}]

    for idx, day in enumerate((d_y, d_t, d_n)):
        s = sun(loc.observer, date=day, tzinfo=TZ)

        twilights[idx]["date_utc"] = str(day)

        # Geometric sunrise/sunset (Sun altitude ~ 0 degrees)
        twilights[idx]["sunrise"] = {"geometric": _to_utc(s["sunrise"])}
        twilights[idx]["sunset"] = {"geometric": _to_utc(s["sunset"])}

        # Civil / nautical / astronomical twilight:
        # dawn() corresponds to morning twilight boundary; dusk() corresponds to evening boundary.
        for twilight, alt in [("civil", 6), ("nautical", 12), ("astronomical", 18)]:
            twilights[idx]["sunrise"][twilight] = _to_utc(
                dawn(loc.observer, date=day, tzinfo=TZ, depression=alt)
            )
            twilights[idx]["sunset"][twilight] = _to_utc(
                dusk(loc.observer, date=day, tzinfo=TZ, depression=alt)
            )

    # -------------------------------------------------------------------------
    # 4) Serialize to JSON (atomic write: write temp then rename)
    # -------------------------------------------------------------------------
    # ISO strings in UTC with trailing 'Z'
    def iso_z(dt: datetime) -> str:
        return dt.astimezone(TZ).isoformat().replace("+00:00", "Z")

    # Convert datetime objects inside twilights to ISO strings for JSON.
    for idx in range(3):
        for sun_position in ("sunrise", "sunset"):
            for twilight in ("geometric", "civil", "nautical", "astronomical"):
                twilights[idx][sun_position][twilight] = iso_z(twilights[idx][sun_position][twilight])

    out = {
        "generated_utc": iso_z(now_utc),
        "site": {
            "lat": latitude,
            "lon": longitude,
            "gps_mode": gps_mode,
            "source": "override" if override_mode else "gps",
        },
        "now_utc": iso_z(now_utc),
        "twilights": twilights,
    }

    # Write compact JSON (small file, faster to parse)
    tmp_path = OUT_JSON.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(out, separators=(",", ":"), indent=4) + "\n")

    # Atomic replace on POSIX
    os.replace(tmp_path, OUT_JSON)

    with OUT_LOG.open("a") as f:
        f.write(
            f"{now_utc.isoformat().replace('+00:00','Z')} "
            f"Updated {OUT_JSON} (lat={latitude}, lon={longitude}, mode={gps_mode}, source={'override' if override_mode else 'gps'})\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())