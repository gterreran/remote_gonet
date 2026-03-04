"""
sun_gate.py
===========

Purpose
-------
Provide a simple "sun gate" for the GONet imaging script (`gonet4.py`).

`gonet4.py` runs on a cron schedule (e.g. every 5 minutes). Early in that script,
we import this module and call `should_image_now(...)`.

This module decides whether we should image *right now* based on a small JSON
table produced by `build_sun_windows.py`.

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
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal


# =============================================================================
# USER-EDITABLE SETTINGS
# =============================================================================

SUN_WINDOWS_PATH = Path("/home/pi/Tools/Sun/sun_windows.json")

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
        A timedelta added to the event time (e.g. -1h, +2h).
    """
    sun_position: SUN_POSITION
    twilight: TWILIGHT_SET
    offset: timedelta = timedelta(0)


# Define the imaging window edges:
#   start_time = START event time + START.offset
#   end_time   = END   event time + END.offset
START = SunEvent("sunset", "civil", offset=timedelta(hours=-1))
END   = SunEvent("sunrise", "nautical", offset=timedelta(hours=+2))

# If anything goes wrong, image anyway.
FAIL_OPEN_IMAGE = True


# =============================================================================
# PUBLIC API
# =============================================================================

def should_image_now() -> bool:
    """
    Decide whether the camera should image now, based on the twilight table.

    Parameters
    ----------
    latitude, longitude, gps_mode
        Not used in this simplified version. Included so gonet4.py can pass GPS
        without special-casing.

    Returns
    -------
    bool
        True  -> proceed with imaging
        False -> skip imaging (exit gonet4.py early)
    """
    now = datetime.now(timezone.utc)

    try:
        # ---------------------------------------------------------------------
        # 1) Load the JSON twilight table
        # ---------------------------------------------------------------------
        data = json.loads(SUN_WINDOWS_PATH.read_text())
        rows = data["twilights"]

        # ---------------------------------------------------------------------
        # 2) Extract candidate START and END timestamps from all 3 rows
        # ---------------------------------------------------------------------
        # Each row contains:
        #   row["sunset"][twilight]  -> ISO string with trailing Z
        #   row["sunrise"][twilight] -> ISO string with trailing Z
        #
        # We gather the three candidates for START and the three candidates for END.
        start_candidates: list[datetime] = []
        end_candidates: list[datetime] = []

        for row in rows:
            # Pull the raw ISO timestamp string for the configured START event.
            start_str = row[START.sun_position][START.twilight]
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            start_candidates.append(start_dt + START.offset)

            # Pull the raw ISO timestamp string for the configured END event.
            end_str = row[END.sun_position][END.twilight]
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            end_candidates.append(end_dt + END.offset)

        # Sort chronologically so we can pick boundaries reliably.
        start_candidates.sort()
        end_candidates.sort()

        # ---------------------------------------------------------------------
        # 3) Choose the window around "now"
        # ---------------------------------------------------------------------
        # We want:
        #   start = latest start <= now
        #   end   = earliest end > start
        #
        # If we can't find those, we fail open (image).
        starts_before_now = [s for s in start_candidates if s <= now]
        if not starts_before_now:
            return True
        start = starts_before_now[-1]  # last one after sorting

        ends_after_start = [e for e in end_candidates if e > start]
        if not ends_after_start:
            return True
        end = ends_after_start[0]  # first one after sorting

        # ---------------------------------------------------------------------
        # 4) Gate decision
        # ---------------------------------------------------------------------
        return (start <= now < end)

    except Exception:
        return bool(FAIL_OPEN_IMAGE)