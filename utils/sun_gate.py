#!/usr/bin/env python3
"""
sun_gate.py
===========

Purpose
-------
Provide a simple "sun gate" for the GONet imaging script (`gonet4.py`).

This module decides whether we should image *right now* based on a small JSON
table produced by `build_sun_windows.py`.

In addition, this module also maintains the JSON cache, which contains
pre-computed twilight event timestamps for yesterday, today, and tomorrow.

Core idea
---------
The JSON contains twilight event timestamps for *three* dates (typically
yesterday/today/tomorrow in UTC), stored as a list of three "rows" under the key
"twilights".

Rather than reasoning about which row is "today", we simply:

1) Extract the 3 candidate START events (e.g., sunset.civil) across all rows.
2) Extract the 3 candidate END events (e.g., sunrise.nautical) across all rows.
3) Apply the configured offsets.
4) Sort the candidates chronologically.
5) Choose:
   - start = latest START time <= now
   - end   = earliest END time  > start
6) If now is within [start, end), we image. Otherwise we skip.

Fail-open philosophy
--------------------
It is better to take images than to miss them.

Therefore:
- If the JSON is missing/unreadable, we return True (image).
- If we cannot compute a sensible window from the candidates, we return True.
- If any parsing/logic error occurs, we return True.

Sun json cache maintenance
--------------------------
- JSON path: /home/pi/Tools/Sun/sun_windows.json  (NOT wiped by gonet4.py)
- If the JSON is missing or older than STALE_AFTER_HOURS, we rebuild it.
- If the JSON is present but the cached site is farther than MAX_SITE_DRIFT_KM
from the current GPS fix, we rebuild it.

"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from astral import LocationInfo
from astral.sun import sun, dawn, dusk

from .gps import GPSFix

# =============================================================================
# USER-EDITABLE SETTINGS
# =============================================================================

SUN_WINDOWS_PATH = Path("/home/pi/Tools/Sun/sun_windows.json")

# Recompute if the JSON is missing OR older than this many hours.
STALE_AFTER_HOURS = 12

# If cached JSON site is farther than this from current GPS, rebuild.
MAX_SITE_DRIFT_KM = 25.0

# Use UTC everywhere to avoid DST/local ambiguity.
TZ = timezone.utc

TWILIGHT_SET = Literal["geometric", "civil", "nautical", "astronomical"]
SUN_POSITION = Literal["sunset", "sunrise"]


@dataclass(frozen=True, slots=True)
class SunEvent:
    """
    Encapsulate an event selection and an optional time offset.

    Attributes
    ----------
    sun_position
        Either "sunset" or "sunrise".
    twilight
        One of: "geometric", "civil", "nautical", "astronomical".
    offset
        Timedelta added to the event time (e.g. -1h, +2h).
    """
    sun_position: SUN_POSITION
    twilight: TWILIGHT_SET
    offset: timedelta = timedelta(0)


# Imaging window edges:
#   start_time = START event + START.offset
#   end_time   = END   event + END.offset
START = SunEvent("sunset", "civil", offset=timedelta(hours=-1))
END   = SunEvent("sunrise", "nautical", offset=timedelta(hours=+2))

FAIL_OPEN_IMAGE = True

# =============================================================================
# Distance helper (haversine)
# =============================================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two points on Earth (km).
    """
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


# =============================================================================
# JSON cache management
# =============================================================================

def _json_is_stale(path: Path, *, now_utc: datetime) -> bool:
    """
    True if JSON is missing or older than STALE_AFTER_HOURS.
    """
    if not path.exists():
        return True
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, TZ)
    except Exception:
        return True
    age = now_utc - mtime
    return age >= timedelta(hours=STALE_AFTER_HOURS)


def _cached_site_far_from_fix(data: dict, *, fix: GPSFix) -> bool:
    """
    Return True if cached JSON 'site' lat/lon differs from current fix by > MAX_SITE_DRIFT_KM.

    If parsing fails, be conservative and return True (force rebuild).
    """
    try:
        site = data.get("site", {})
        lat0 = float(site.get("lat", 0.0))
        lon0 = float(site.get("lon", 0.0))
        dist = _haversine_km(lat0, lon0, fix.latitude, fix.longitude)
        return dist > MAX_SITE_DRIFT_KM
    except Exception:
        return True


def _compute_twilights_3day(*, latitude: float, longitude: float, now_utc: datetime) -> dict:
    """
    Compute twilight events for yesterday/today/tomorrow (UTC), return JSON-serializable dict.
    """
    loc = LocationInfo(
        name="GONet",
        region="site",
        timezone="UTC",
        latitude=latitude,
        longitude=longitude,
    )

    d_y = (now_utc - timedelta(days=1)).date()
    d_t = now_utc.date()
    d_n = (now_utc + timedelta(days=1)).date()

    def _to_utc(dt: datetime) -> datetime:
        return dt.astimezone(TZ).replace(microsecond=0)

    twilights: list[dict] = [{}, {}, {}]

    for idx, day in enumerate((d_y, d_t, d_n)):
        s = sun(loc.observer, date=day, tzinfo=TZ)

        twilights[idx]["date_utc"] = str(day)

        twilights[idx]["sunrise"] = {"geometric": _to_utc(s["sunrise"])}
        twilights[idx]["sunset"]  = {"geometric": _to_utc(s["sunset"])}

        for twilight, alt in [("civil", 6), ("nautical", 12), ("astronomical", 18)]:
            twilights[idx]["sunrise"][twilight] = _to_utc(
                dawn(loc.observer, date=day, tzinfo=TZ, depression=alt)
            )
            twilights[idx]["sunset"][twilight] = _to_utc(
                dusk(loc.observer, date=day, tzinfo=TZ, depression=alt)
            )

    def iso_z(dt: datetime) -> str:
        return dt.astimezone(TZ).isoformat().replace("+00:00", "Z")

    # Convert datetimes to ISO strings
    for idx in range(3):
        for sun_position in ("sunrise", "sunset"):
            for twilight in ("geometric", "civil", "nautical", "astronomical"):
                twilights[idx][sun_position][twilight] = iso_z(twilights[idx][sun_position][twilight])

    out = {
        "generated_utc": iso_z(now_utc),
        "site": {
            "lat": latitude,
            "lon": longitude,
            "source": "gonet_fix",
        },
        "twilights": twilights,
    }
    return out


def _write_json_atomic(path: Path, payload: dict) -> None:
    """
    Atomic JSON write (temp then replace).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), indent=4) + "\n")
    tmp.replace(path)


def ensure_sun_windows_json(
    *,
    fix: GPSFix,
    logger,
) -> tuple[bool, dict | None]:
    """
    Ensure sun_windows.json exists and is reasonably fresh for this site.

    Parameters
    ----------
    fix
        GPS fix from gonet4.py (already validated).
    logger
        gonet4.py logger (we do not maintain a separate sun log).

    Returns
    -------
    (bool, dict | None)
        (ok, data) where ok indicates that data is available for use.
        If ok is False, data may be None.
    """
    now_utc = datetime.now(TZ)

    # Decide if rebuild needed.
    rebuild = _json_is_stale(SUN_WINDOWS_PATH, now_utc=now_utc)

    data: dict | None = None
    if not rebuild:
        try:
            data = json.loads(SUN_WINDOWS_PATH.read_text())
            if _cached_site_far_from_fix(data, fix=fix):
                logger.warning(
                    "sun_gate: cached site too far from current GPS -> rebuild (threshold_km=%.1f)",
                    MAX_SITE_DRIFT_KM,
                )
                rebuild = True
        except Exception:
            rebuild = True
            data = None

    if rebuild:
        try:
            payload = _compute_twilights_3day(
                latitude=fix.latitude,
                longitude=fix.longitude,
                now_utc=now_utc,
            )
            _write_json_atomic(SUN_WINDOWS_PATH, payload)
            data = payload
            logger.info(
                "sun_gate: updated %s (lat=%.6f lon=%.6f stale_after_h=%.1f)",
                SUN_WINDOWS_PATH,
                fix.latitude,
                fix.longitude,
                float(STALE_AFTER_HOURS),
            )
        except Exception as e:
            logger.exception("sun_gate: failed updating sun windows JSON: %s", e)
            return (False, None)

    return (True, data)


# =============================================================================
# Gate decision (public API used by gonet4.py)
# =============================================================================

def should_image_now(
    *,
    fix: GPSFix,
    logger,
) -> bool:
    """
    Decide whether the camera should image now.

    This function:
    - Ensures sun_windows.json exists/updated if needed (using fix from gonet4.py)
    - Reads twilight candidates and computes the "night window"
    - Returns True to image, False to skip

    Fail-open: returns True if anything fails.
    """
    now = datetime.now(TZ)

    try:
        ok, data = ensure_sun_windows_json(fix=fix, logger=logger, now_utc=now)
        if not ok or not data:
            return bool(FAIL_OPEN_IMAGE)

        rows = data["twilights"]

        start_candidates: list[datetime] = []
        end_candidates: list[datetime] = []

        for row in rows:
            start_str = row[START.sun_position][START.twilight]
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(TZ)
            start_candidates.append(start_dt + START.offset)

            end_str = row[END.sun_position][END.twilight]
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(TZ)
            end_candidates.append(end_dt + END.offset)

        start_candidates.sort()
        end_candidates.sort()

        starts_before_now = [s for s in start_candidates if s <= now]
        if not starts_before_now:
            return True
        start = starts_before_now[-1]

        ends_after_start = [e for e in end_candidates if e > start]
        if not ends_after_start:
            return True
        end = ends_after_start[0]

        should = (start <= now < end)
        logger.info(
            "sun_gate: now=%s start=%s end=%s -> %s",
            now.isoformat().replace("+00:00", "Z"),
            start.isoformat().replace("+00:00", "Z"),
            end.isoformat().replace("+00:00", "Z"),
            "IMAGE" if should else "SKIP",
        )
        return should

    except Exception:
        return bool(FAIL_OPEN_IMAGE)


# =============================================================================
# Optional: CLI for debugging (no cron required)
# =============================================================================

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Debug sun gate decision (no cron needed).")
    p.add_argument("--lat", type=float, required=True, help="Latitude (deg)")
    p.add_argument("--lon", type=float, required=True, help="Longitude (deg)")
    p.add_argument("--gps-mode", type=int, default=3, help="GPS mode (3 = ok)")
    return p.parse_args()


def _main_cli() -> int:
    args = _parse_args()

    # Small, minimal logger for CLI use; gonet4.py will pass its own logger.
    import logging
    logger = logging.getLogger("sun_gate_cli")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
        logger.addHandler(h)

    fix = GPSFix(ok=(args.gps_mode == 3), gps_mode=args.gps_mode, latitude=args.lat, longitude=args.lon)
    res = should_image_now(fix=fix, logger=logger)
    print("IMAGE" if res else "SKIP")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())