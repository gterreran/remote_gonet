Refactoring of original ``gonet4.py``
-------------------------------------

Refactor at a glance (old → new)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The original ``gonet4.py`` (see `here <https://github.com/Wied58/gonet4/blob/main/gonet4.py>`__)
functionality has been preserved while modernizing
the structure and reliability of the code. The main changes are architectural
rather than behavioral.

Old (legacy script)
    - Single monolithic script (~1000+ lines)
    - Global variables for configuration
    - ``sys.argv`` parsing with manual string handling
    - String-based file paths
    - Inline GPS acquisition logic
    - Inline EXIF + overlay formatting
    - Hard-coded Bayer tail size (magic number)
    - ``print`` statements and manual log truncation
    - Post-processing scanned *all* files in scratch
    - Saturation check using incorrect byte interpretation

New (refactored architecture)
    - Modular structure with dedicated ``utils/`` modules
    - Configuration stored in a typed ``AcquisitionConfig`` dataclass
    - ``argparse`` for CLI parsing and overrides
    - ``pathlib.Path`` for filesystem operations
    - GPS acquisition wrapped in a safe helper returning structured results
    - Centralized metadata + EXIF construction
    - Automatic Bayer tail detection using JPEG EOI marker
    - Python logging with rotating log files
    - Post-processing limited to images captured in the current run
    - Saturation check removed (incorrect and computationally expensive)

Overview
^^^^^^^^

The original ``gonet4.py`` was a single, monolithic script that mixed together:

- configuration parsing (``sys.argv`` + manual prompts + key=value file parsing)
- GPS acquisition (side-effectful import of ``FetchGPS``)
- status markers (shelling out to ``rm -rf`` + ``touch``)
- directory setup and scratch recovery
- camera capture loop (PiCamera setup + EXIF tags)
- post-processing pipeline (overlay banner + EXIF preservation + Bayer append + thumbnail)
- log file management (manual “keep last N lines” rotation)

This refactor keeps the *same operational behavior* (cron-safe, fail-open) while turning
``gonet4.py`` into a readable orchestration layer and moving specific responsibilities
into dedicated modules.

High-level restructuring
^^^^^^^^^^^^^^^^^^^^^^^^

The new ``gonet4.py`` is now mostly an “orchestrator”:

- resolve configuration
- acquire GPS (fail-open)
- perform setup checks and scratch recovery
- capture images to scratch
- post-process only the images captured in this run
- write structured logs and status markers
- optional post-run actions (e.g. flash drive migration, sun gate)

All heavy logic is moved into ``utils/`` modules with clear, testable entrypoints.

Module breakdown (new)
^^^^^^^^^^^^^^^^^^^^^^

``utils.config``
    Centralizes *all* acquisition defaults and overrides in an ``AcquisitionConfig`` dataclass.

    - Replaces global variables (``shutter_speed``, ``number_of_images``, ``ISO``, ``use_gps``).
    - Supports the legacy “config file path” argument and the ``manual`` mode.
    - Adds explicit validation bounds (ISO, shutter speeds, number of images).
    - Uses ``argparse`` instead of raw ``sys.argv`` parsing.
    - Uses ``parse_known_args()`` so the main script can add its own flags
      (e.g. ``--quiet``, ``--sun-gate``, ``--flashdrive-copy``) without breaking config parsing.
    - Adds support for *multiple shutter speeds* via comma-separated values
      (e.g. ``--shutter-speed 1000000,2000000,6000000``).

``utils.gps``
    Wraps the legacy GPS workflow into a cron-safe function:

    - ``acquire_gps_fix(use_gps=..., set_status=...) -> GPSFix``
    - Preserves the reality that ``FetchGPS`` performs acquisition at *import time*,
      but isolates that side effect to a single place.
    - Returns a structured result (ok/mode/lat/lon/alt/acquire time/message) and never raises.
    - Fail-open behavior preserved: if GPS fails, imaging proceeds and overlay reports
      ``GPS BYPASSED``.

``utils.imaging_meta``
    Centralizes “run metadata” creation:

    - Overlay banner text formatting
    - EXIF GPS formatting helpers
    - Camera EXIF tag dictionary assembly
    - Banner rendering (PIL) via ``write_overlay_banner(...)``

    This replaces scattered formatting logic and ensures consistent overlay/EXIF content.

``utils.imaging_pipeline``
    Encapsulates post-processing for a single capture:

    - Preserve EXIF from the scratch JPG
    - Paste overlay banner
    - Save composed full-size JPEG
    - Append the RAW Bayer tail
    - Create a thumbnail
    - Optionally delete scratch file

    This replaces the legacy post-processing block that iterated over *all* scratch files,
    used hard-coded tail sizes, and mixed shell commands with image logic.

``utils.logging``
    Replaces manual log file truncation with Python’s rotating log handler:

    - Status markers preserved (``/home/pi/Tools/Status`` wipe + touch)
    - Rotating log file at ``/home/pi/Tools/Camera/gonet.log`` via ``RotatingFileHandler``
    - Adds ``--quiet`` mode to suppress console spam for cron runs while still logging to file

``utils.setup``
    Isolates filesystem and “run environment” concerns:

    - canonical ``Path`` constants (``SCRATCH_DIR``, ``IMAGE_DIR``, ``THUMBS_DIR``)
    - ``ensure_dirs(...)`` and ``recover_scratch_leftovers(...)``
    - ``version_check()`` and ``cap_check()``
    - ``check_free_space(...)`` with legacy “percent free” behavior

Modernization changes (mechanical refactor)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Argparse instead of ``sys.argv``
"""""""""""""""""""""""""""""""

Legacy behavior:
    ``gonet4.py`` treated ``sys.argv[1]`` as either a config filepath or the magic word
    ``manual``. It also did not support “true” flags cleanly.

New behavior:
    - ``utils.config`` owns config parsing.
    - Acquisition settings accept both legacy config files and explicit CLI overrides
      (``--iso``, ``--n-images``, ``--shutter-speed``, ``--no-gps``).
    - ``gonet4.py`` adds script-level flags (``--quiet``, etc.) without interfering with config parsing.

Net result:
    - Backwards compatible with “``gonet4.py default``” and “``gonet4.py manual``”
    - More discoverable and safer for remote operation

``pathlib.Path`` everywhere
"""""""""""""""""""""""""""

Legacy behavior:
    The script used string paths and manual string concatenation.

New behavior:
    Canonical paths are defined as ``Path`` constants in ``utils.setup`` and passed around as ``Path`` objects.

Net result:
    Less error-prone path manipulation, cleaner logs, and simpler file operations.

Separation of concerns and “cron-safe” fail-open philosophy
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

The refactor preserves the field philosophy: *it is better to take images than to crash*.

- GPS acquisition returns a result object and never raises.
- Scratch cleanup is best-effort and noisy in logs, but does not abort imaging.
- Disk-full detection returns early and disables the crontab (legacy behavior preserved).
- Errors in optional features are handled so imaging can proceed (fail-open).

Logging improvements and ``--quiet``
"""""""""""""""""""""""""""""""""""

Legacy behavior:
    - print-based console output
    - manual file append + manual “keep last N lines” rotation
    - hard to grep consistently and noisy under cron

New behavior:
    - All messages go through a structured logger.
    - Log format includes UTC-like timestamps and severity:
      ``YYYY-mm-ddTHH:MM:SSZ LEVEL message``
    - File rotation is automatic (size-based) and keeps a small number of backups.
    - ``--quiet`` disables console output while keeping full logs on disk.

Post-processing only what was captured in this run
""""""""""""""""""""""""""""""""""""""""""""""""""

Legacy behavior:
    Post-processing iterated through all ``.jpg`` in scratch at the end of the run. This mixed
    recovery leftovers with “this run’s” images and could lead to confusing behavior if scratch
    contained leftover files.

New behavior:
    ``gonet4.py`` tracks exactly what it captured in ``captured_files`` and post-processes
    only that list. Scratch recovery still exists, but is explicitly handled earlier and logged
    as a recovery event.

Overlay banner creation moved out of main script
"""""""""""""""""""""""""""""""""""""""""""""""

Legacy behavior:
    One ``foreground.jpeg`` was created once per run, so the overlay timestamp could lag and was
    not guaranteed to be per-image accurate.

New behavior:
    - Overlay text + EXIF are generated in ``utils.imaging_meta``.
    - A unique overlay banner is created per image (or per capture record), ensuring the timestamp
      updates and metadata assembly is centralized.

Removal of the saturation check
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The legacy script included an ``is_saturated()`` function that attempted to inspect the Bayer
bytes and decide if the image was saturated. This was removed in the refactor because:

- It was computationally expensive on a Pi Zero-class CPU (extra reads and NumPy work).
- The legacy implementation was not valid: the code read the raw tail as ``uint8`` and compared
  values to 4095. Individual bytes cannot exceed 255, so ``array > 4095`` is never true.
  In other words, the check could not function as written.
- A correct saturation check would require unpacking packed 12-bit Bayer samples, which is far
  more expensive than the operational value it provided during routine acquisition.

If saturation diagnostics are needed in the future, they should live in an offline analysis tool
(or be implemented as an optional, explicitly-enabled mode).

Bayer tail handling: from hard-coded magic number to robust detection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Legacy behavior:
    The script appended a hard-coded number of bytes from the scratch file
    (``tail -c 18711040``) to the output JPEG, assuming the Bayer tail is always that size.

This is brittle because the Bayer tail size can vary with camera model, sensor mode, resolution,
firmware, or PiCamera behavior.

New behavior:
    ``utils.imaging_pipeline`` detects the Bayer tail by parsing the JPEG structure:

    - locate the final JPEG end-of-image marker (EOI = ``0xFF 0xD9``)
    - treat everything after EOI as “tail”
    - append the entire tail to the composited output JPEG

This removes the “magic number” and makes the pipeline resilient to tail size changes while
preserving the legacy artifact format expected by downstream tooling.

(Additionally, the module includes a best-effort detection of the common ``BRCM`` header region
to estimate the payload size, while still appending the full tail for compatibility.)

Preserved legacy behaviors (intentional)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Even though the implementation is modernized, several operational behaviors were intentionally preserved:

- Status marker directory semantics (wipe + touch a single marker file).
- PiCamera ``CAPTURE_TIMEOUT`` patch to support long exposures.
- Scratch crash recovery:
  - delete zero-length files
  - move leftover ``.jpg`` from scratch into ``IMAGE_DIR`` (fail-open “save the data” behavior)
- Version and lens-cap status are still derived from the same filesystem conventions.
- Filename format and UTC-based naming remain consistent with the legacy script.