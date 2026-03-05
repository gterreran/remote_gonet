"""
utils.gps
=========

GPS acquisition for gonet4.py.

Notes
----------
The current GPS module FetchGPS performs acquisition *at import time*:
import FetchGPS triggers GPS polling and then sets module globals:
    GPSMode, GPSLat, GPSLong, GPSAlt, ...

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Callable

FETCHGPS_PATH = Path("/home/pi/Tools/FetchGPS")

@dataclass(frozen=True)
class GPSFix:
    """
    Result container for GPS acquisition.

    Parameters
    ----------
    ok
        True if we consider the fix usable (GPSMode == 3).
    gps_mode
        Mode value from FetchGPS (typically 0..3). When bypassed/failed, may be 0.
    latitude
        Latitude in degrees.
    longitude
        Longitude in degrees.
    altitude
        Altitude in meters.
    acquire_seconds
        Wall-clock seconds spent acquiring GPS (import time).
    message
        Short human-readable message for logs.
    """
    ok: bool
    gps_mode: int
    latitude: float
    longitude: float
    altitude: float
    acquire_seconds: float
    message: str = ""


def acquire_gps_fix(
    *,
    use_gps: bool,
    set_status: Callable[[str], None] | None = None,
) -> GPSFix:
    """
    Attempt to acquire a GPS fix using the existing FetchGPS module.

    This function is designed to be "cron-safe":
    - If anything fails, it returns ok=False and does not raise.
    - If use_gps is False, it returns ok=False with a bypass message.

    Parameters
    ----------
    use_gps
        If False, bypass GPS acquisition entirely.
    set_status
        Optional callback (e.g., gonet4.set_status) to set Status markers.
        If provided, we will set_status("FetchGPS") before acquisition.

    Returns
    -------
    GPSFix
        Structured result of the attempt.
    """
    if not use_gps:
        return GPSFix(
            ok=False,
            gps_mode=0,
            latitude=0.0,
            longitude=0.0,
            altitude=0.0,
            acquire_seconds=0.0,
            message="GPS bypassed by configuration.",
        )

    if set_status is not None:
        set_status("FetchGPS")

    t0 = time.perf_counter()

    # Make FetchGPS importable.
    if FETCHGPS_PATH not in sys.path:
        sys.path.insert(0, str(FETCHGPS_PATH))

    try:
        import FetchGPS  # type: ignore
    except Exception as e:
        dt = time.perf_counter() - t0
        return GPSFix(
            ok=False,
            gps_mode=0,
            latitude=0.0,
            longitude=0.0,
            altitude=0.0,
            acquire_seconds=dt,
            message=f"FetchGPS import failed: {e!r}",
        )

    dt = time.perf_counter() - t0

    try:
        gps_mode = int(getattr(FetchGPS, "GPSMode", 0))
        latitude = float(getattr(FetchGPS, "GPSLat", 0.0))
        longitude = float(getattr(FetchGPS, "GPSLong", 0.0))
        altitude = float(getattr(FetchGPS, "GPSAlt", 0.0))
    except Exception as e:
        return GPSFix(
            ok=False,
            gps_mode=0,
            latitude=0.0,
            longitude=0.0,
            altitude=0.0,
            acquire_seconds=dt,
            message=f"FetchGPS globals unreadable: {e!r}",
        )

    ok = (gps_mode == 3)
    msg = "GPS fix OK (3D)" if ok else f"GPS fix not OK (mode={gps_mode})"

    return GPSFix(
        ok=ok,
        gps_mode=gps_mode,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        acquire_seconds=dt,
        message=msg,
    )