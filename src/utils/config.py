#!/usr/bin/env python3
"""
utils.config
============

Isolate all configuration/default-parameter logic for gonet4.py.

"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# =============================================================================
# Default acquisition parameters (edit here)
# =============================================================================

DEFAULT_SHUTTER_SPEED = 6_000_000
DEFAULT_NUMBER_OF_IMAGES = 5
DEFAULT_ISO = 800
DEFAULT_USE_GPS = True

# Safeguards?
MIN_SHUTTER_SPEED = 100_000        # 100 ms I (I think this might still be too fast, consider increasing it at least to 200ms)
MAX_SHUTTER_SPEED = 30_000_000  # 30 s (very generous)
MIN_ISO = 50
MAX_ISO = 3200
MIN_N_IMAGES = 1
MAX_N_IMAGES = 50

DEFAULT_WHITE_BALANCE_GAINS = (3.35, 1.59)
DEFAULT_DRC_STRENGTH = "off"
DEFAULT_BRIGHTNESS = 50

@dataclass
class AcquisitionConfig:
    """
    AcquisitionConfig
    -----------------

    This dataclass replaces the original set of global variables in gonet4.py
    (shutter_speed, number_of_images, ISO, use_gps) to make defaults and overrides
    easier to reason about.

    Parameters
    ----------
    shutter_speed : list[int]
        Shutter speed(s) in microseconds. We allow multiple speeds to be specified.
    number_of_images : int
        Number of images to capture per run.
    iso : int
        Camera ISO.
    use_gps : bool
        If True, gonet4.py attempts GPS acquisition via FetchGPS.
    source : str
        Human-readable label used for logging (default/manual/path).

    """
    shutter_speed: list[int] = field(default_factory=lambda: [DEFAULT_SHUTTER_SPEED])
    number_of_images: int = DEFAULT_NUMBER_OF_IMAGES
    iso: int = DEFAULT_ISO
    use_gps: bool = DEFAULT_USE_GPS
    source: str = "default"

    white_balance_gains: Any = DEFAULT_WHITE_BALANCE_GAINS
    drc: str = DEFAULT_DRC_STRENGTH
    brightness: int = DEFAULT_BRIGHTNESS


# -----------------------------------------------------------------------------
# Parsing helpers
# -----------------------------------------------------------------------------

def _parse_shutter_speeds(raw: str) -> list[int]:
    """
    Parse shutter speed(s) in microseconds.

    Accepts:
    - "6000000"
    - "1000000,2000000,3000000"

    Returns
    -------
    list[int]
        Non-empty list of validated shutter speeds (µs).

    Raises
    ------
    ValueError
        If parsing fails or any value is out of bounds.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("shutter_speed is empty")

    out: list[int] = []
    for p in parts:
        x = int(p)
        out.append(_validate_int("shutter_speed", x, MIN_SHUTTER_SPEED, MAX_SHUTTER_SPEED))

    return out


def parse_bool(value: str) -> bool:
    """
    Parse a human-friendly boolean string.

    Parameters
    ----------
    value : str
        Input text.

    Returns
    -------
    bool
        Parsed boolean.
    """
    v = value.strip().lower()
    if v in {"false", "0", "f", "n", "no", "nope", "nyet", "of course not", "no way"}:
        return False
    return True


def _validate_int(name: str, x: int, lo: int, hi: int) -> int:
    """
    Validate an integer is within bounds.

    Parameters
    ----------
    name : str
        Parameter name (for error messages).
    x : int
        Value to validate.
    lo : int
        Minimum acceptable value.
    hi : int
        Maximum acceptable value.

    Returns
    -------
    int
        Validated value.

    Raises
    ------
    ValueError
        If the value is out of bounds.
    """
    if x < lo or x > hi:
        raise ValueError(f"{name}={x} out of bounds [{lo}, {hi}]")
    return x


def apply_overrides(cfg: AcquisitionConfig, overrides: dict[str, str]) -> AcquisitionConfig:
    """
    Apply key/value overrides onto an AcquisitionConfig.

    Unknown keys are ignored (fail-open), consistent with field deployments.

    Parameters
    ----------
    cfg : AcquisitionConfig
        Base config to modify.
    overrides : dict[str, str]
        Keys/values parsed from config file.

    Returns
    -------
    AcquisitionConfig
        Updated config.
    """
    for key, raw in overrides.items():
        if key == "number_of_images":
            cfg.number_of_images = _validate_int("number_of_images", int(raw), MIN_N_IMAGES, MAX_N_IMAGES)
        elif key == "shutter_speed":
            cfg.shutter_speed = _parse_shutter_speeds(raw)
        elif key == "ISO":
            cfg.iso = _validate_int("ISO", int(raw), MIN_ISO, MAX_ISO)
        elif key == "use_gps":
            cfg.use_gps = parse_bool(raw)
        else:
            # Fail-open: ignore unknown keys rather than abort imaging.
            # Defaults are always present, so missing keys are not an issue,
            # and extra keys may be added in the future without breaking old configs.
            pass

    return cfg


def load_config_file(path: Path) -> dict[str, str]:
    """
    Load a legacy key=value config file.

    Lines that are blank or start with '#' are ignored.

    Parameters
    ----------
    path : Path
        Config file path.

    Returns
    -------
    dict[str, str]
        Parsed key/value map.

    Raises
    ------
    FileNotFoundError
        If path does not exist.
    """
    text = path.read_text()
    out: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, val = [x.strip() for x in line.split("=", 1)]
        if key:
            out[key] = val

    return out


def prompt_manual_config() -> AcquisitionConfig:
    """
    Interactive manual prompt mode.

    Returns
    -------
    AcquisitionConfig
        User-provided settings.

    """
    cfg = AcquisitionConfig(source="manual")
    cfg.number_of_images = _validate_int("number_of_images", int(input("Please Enter Your Desired Number of Images: ")),
                                        MIN_N_IMAGES, MAX_N_IMAGES)
    cfg.shutter_speed = _parse_shutter_speeds(input("Please Enter Your Desired Shutter Speed(s) in Microseconds (comma-separated for multiple): "))
    cfg.iso = _validate_int("ISO", int(input("Please Enter Your Desired ISO: ")), MIN_ISO, MAX_ISO)

    gps = input("Do you want gps data? ")
    cfg.use_gps = parse_bool(gps)
    return cfg


def build_argparser() -> argparse.ArgumentParser:
    """
    Build argparse parser for gonet4.py.

    Returns
    -------
    argparse.ArgumentParser
        Parser.
    """
    p = argparse.ArgumentParser(
        description="GONet imaging script (config handling only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument(
        "config",
        nargs="?",
        default="default",
        help="Config file path, or 'manual', or omit for defaults.",
    )
    p.add_argument("--shutter-speed", type=str, default=None, help="Override shutter speed in microseconds (comma-separated for multiple).")
    p.add_argument("--iso", type=int, default=None, help="Override ISO.")
    p.add_argument("--n-images", type=int, default=None, help="Override number_of_images.")
    p.add_argument("--no-gps", action="store_true", help="Bypass GPS acquisition.")
    return p


def resolve_config_from_cli(argv: list[str] | None = None) -> AcquisitionConfig:
    """
    Resolve the final acquisition config from CLI arguments.

    Precedence (highest last):
    1) defaults
    2) config file (if provided)
    3) CLI flags (--iso, --n-images, --shutter-speed, --no-gps)

    Parameters
    ----------
    argv : list[str] | None
        Override argv for testing. If None, argparse uses sys.argv.

    Returns
    -------
    AcquisitionConfig
        Final configuration.

    Raises
    ------
    FileNotFoundError
        If a config path was provided but does not exist.
    ValueError
        If provided values fail basic validation.
    """
    # We use parse_known_args() so gonet4.py can define its own flags
    # (e.g. --quiet) without breaking config parsing.
    args, _unknown = build_argparser().parse_known_args(argv)

    # Base defaults
    cfg = AcquisitionConfig(source="default")

    # Apply config selection
    if args.config == "manual":
        cfg = prompt_manual_config()
    elif args.config not in {"default", "", None}:
        path = Path(args.config)
        cfg.source = str(path)
        overrides = load_config_file(path)
        cfg = apply_overrides(cfg, overrides)

    # Apply CLI overrides (highest priority)
    if args.shutter_speed is not None:
        cfg.shutter_speed = _parse_shutter_speeds(args.shutter_speed)
    if args.iso is not None:
        cfg.iso = _validate_int("ISO", args.iso, MIN_ISO, MAX_ISO)
    if args.n_images is not None:
        cfg.number_of_images = _validate_int("number_of_images", args.n_images, MIN_N_IMAGES, MAX_N_IMAGES)
    if args.no_gps:
        cfg.use_gps = False

    return cfg