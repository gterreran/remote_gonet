#!/usr/bin/env python3
"""
sun_gate.py
===========

Provide a minimal "sun gate" for the GONet imaging script (``gonet4.py``).

This module answers a single question:

    Should we image *right now*?

Decision rule
-------------
Given a GPS fix (latitude/longitude) and the current UTC time, compute the Sun's
altitude angle (a.k.a. elevation). If the Sun altitude is **below** a configured
threshold, we image; otherwise we skip.

Typical thresholds
------------------
- Geometric sunrise/sunset: 0 degrees
- Civil twilight      : -6 degrees
- Nautical twilight   : -12 degrees
- Astronomical twilight: -18 degrees

Fail-open philosophy
--------------------
It is better to take images than to miss them.

Therefore:
- If Astral computation fails for any reason, return True (image) by default.

Public API
----------
- ``should_image_now(fix, logger, sun_altitude_limit_deg=-12.0) -> bool``

"""

from __future__ import annotations

from datetime import datetime, timezone

from astral import Observer
from astral.sun import elevation

from .gps import GPSFix

# =============================================================================
# USER-EDITABLE SETTINGS
# =============================================================================

DEFAULT_SUN_ALTITUDE_LIMIT_DEG = 0

# Fail-open: image if anything unexpected happens
FAIL_OPEN_IMAGE = True


# =============================================================================
# Public API
# =============================================================================

def should_image_now(
    *,
    fix: GPSFix,
    logger,
    sun_altitude_limit_deg: float = DEFAULT_SUN_ALTITUDE_LIMIT_DEG,
    fail_open: bool = FAIL_OPEN_IMAGE,
) -> bool:
    """
    Decide whether the camera should image now based on Sun altitude.

    Parameters
    ----------
    fix : GPSFix
        GPS fix container providing latitude/longitude and an ``ok`` flag.
    logger : logging.Logger
        Logger from ``gonet4.py`` (or a compatible logger).
    sun_altitude_limit_deg : float
        Image if the Sun altitude (degrees) is <= this value.
        Example: -12.0 corresponds to nautical twilight.
    fail_open : bool
        If True, return True (image) when GPS is not OK or any error occurs.

    Returns
    -------
    bool
        True if imaging should proceed now, False if it should be skipped.
    """
    try:
        lat = float(fix.latitude)
        lon = float(fix.longitude)

        # Current UTC time
        now_utc = datetime.now(timezone.utc)

        # Compute Sun altitude (degrees). Positive = above horizon.
        obs = Observer(latitude=lat, longitude=lon)
        alt_deg = float(elevation(obs, now_utc))

        should = (alt_deg <= float(sun_altitude_limit_deg))

        logger.info(
            "sun_gate: now_utc=%s lat=%.6f lon=%.6f sun_alt_deg=%.3f limit_deg=%.3f -> %s",
            now_utc.isoformat().replace("+00:00", "Z"),
            lat,
            lon,
            alt_deg,
            float(sun_altitude_limit_deg),
            "IMAGE" if should else "SKIP",
        )
        return should

    except Exception as e:
        logger.exception("sun_gate: error computing sun altitude; fail_open=%s err=%r", fail_open, e)
        return bool(fail_open)
