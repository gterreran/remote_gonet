======================================
GONet Extensions for Remote Deployment
======================================

This repository contains extensions and refactorings of the original GONet camera
software, designed to support **remote deployment** and **unattended operation**.

Table of Contents
=================
- :ref:`installation`

    - :ref:`quick_install`
    - :ref:`installer_actions`

- :ref:`file_descriptions`

    - :ref:`refactoring`
    - :ref:`new_features`

        - :ref:`multiple_exposure_times`
        - :ref:`sun_gate`
        - :ref:`flash_drive_copy`

    - :ref:`USB_patch`
    - :ref:`boot_patch`
    - :ref:`extra`


.. _installation:
Installation
============

The remote GONet extensions can be installed directly on a camera using a
single bootstrap script. The installer downloads the required files from
GitHub and deploys them into the correct locations on the Raspberry Pi.

No manual cloning of the repository is required.

.. _quick_install:
Quick install
-------------

Run the following commands on the GONet camera:

::

    curl -L -o setup_remote_gonet.sh \
        https://raw.githubusercontent.com/gterreran/remote_gonet/main/setup_remote_gonet.sh

    chmod +x setup_remote_gonet.sh

    sudo ./setup_remote_gonet.sh

.. _installer_actions:
What the installer does
-----------------------

The installer performs the following actions automatically:

1. **Install Python dependency**

   Installs the required Python package::

       astral

   The Astral library is used by the **sun gate** feature to compute
   the Sun's altitude based on GPS coordinates and time, without 
   relying on internet access.

2. **Install camera software**

   Downloads and installs the updated imaging code into::

       /home/pi/Tools/Camera/

   including::

       gonet4.py (refactored with new features)
       utils/

3. **Install remote cron configuration**

   Installs the remote cron backup file::

       /home/pi/Tools/Crontab/CronRemoteBackup.txt

   This cron configuration is used by the remote control mode.

4. **Apply system patches**

   Two system patches are applied:

   - ``patch_usb_mount.sh``  
     Installs the flexible USB auto-mount system for flash drives.

   - ``patch_remote_bootup.sh``  
     Modifies ``/etc/rc.local`` so the camera loads the remote cron
     configuration at boot.

5. **Install the slimmed down remote camera web interface**

   Replaces the default camera webpage with the simplified remote interface::

       /home/pi/Tools/Web/camera/index.php

   The previous file is automatically backed up.

Result
^^^^^^

After installation:

- the camera software is updated
- required Python dependencies are installed
- the remote cron configuration is installed
- the start up script is patched to load the remote cron configuration
- USB flash drives are automatically mounted
- the slimmed down remote camera control webpage is installed

The system will continue operating normally and will use the new remote
configuration on the next reboot.

.. _file_descriptions:
File descriptions and refactoring details
=========================================

.. _refactoring:
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
    - Python logging with rotating log files
    - Post-processing limited to images captured in the current run
    - Saturation check removed (incorrect and computationally expensive)

The new ``gonet4.py`` is now mostly an “orchestrator”, while all heavy
logic is moved into ``utils/`` modules with clear, testable entrypoints.

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
    - Added UTC timestamp in EXIF data (legacy script only had it in the filename and overlay text)
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
    and mixed shell commands with image logic.

``utils.logging``
    Replaces manual log file truncation with Python's rotating log handler:

    - Status markers preserved (``/home/pi/Tools/Status`` wipe + touch)
    - Rotating log file at ``/home/pi/Tools/Camera/gonet.log`` via ``RotatingFileHandler``
    - Adds ``--quiet`` mode to suppress console spam for cron runs while still logging to file

``utils.setup``
    Isolates filesystem and “run environment” concerns:

    - canonical ``Path`` constants (``SCRATCH_DIR``, ``IMAGE_DIR``, ``THUMBS_DIR``)
    - ``ensure_dirs(...)`` and ``recover_scratch_leftovers(...)``
    - ``version_check()`` and ``cap_check()``
    - ``check_free_space(...)`` now look for a certain amount of free space in bytes
      (defined as a constnt) rather than a percentage.

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
    recovery leftovers with “this run's” images and could lead to confusing behavior if scratch
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

Includin UTC timestamp in EXIF data
"""""""""""""""""""""""""""""""""""

Legacy behavior:
    The original script did not include the UTC timestamp in the EXIF data.
    It only included the timestamp in the overlay banner text and the filename.

New behavior:
    The refactored system includes the UTC timestamp in the EXIF data. This
    ensures that the timestamp is preserved in the image metadata and
    does not rely solely on the filename for time information.

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

.. new_features:
New features
------------

In addition to the structural refactoring described above, several new
capabilities were introduced to improve operational flexibility for remote
deployments and long-term unattended operation.

.. multiple_exposure_times:
Multiple exposure times
^^^^^^^^^^^^^^^^^^^^^^^

The original ``gonet4.py`` supported only a **single shutter speed** per run.
Each invocation of the script would capture ``number_of_images`` frames using
that single exposure value.

The refactored system allows **multiple exposure times to be specified in a
single run**.

This is implemented through the configuration system in ``utils.config``.
The ``shutter_speed`` parameter now accepts **a list of exposure times** rather
than a single value. The list is parsed from a comma-separated string.

Example:

.. code-block:: bash

   gonet4.py --shutter-speed 1000000,3000000,6000000

In this example 1,3 and 6 seconds exposures will be captured.

Now, for each exposure value, the script captures ``number_of_images`` frames.
Therefore the total number of images produced in a run is:

.. code-block:: text

   total_images = len(shutter_speed_list) x number_of_images

This enables a simple **exposure bracketing strategy** without
requiring multiple cron jobs or configuration changes.

The legacy configuration file format remains compatible:

.. code-block:: text

   shutter_speed = 1000000,3000000,6000000

.. sun_gate:
Sun gate (daylight skip) based on Sun altitude
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The *sun gate* feature allows ``gonet4.py`` to skip imaging during daytime
while preserving the "fail-open" philosophy (it is better to take images than to
miss them).

The current implementation is intentionally simple: the gate simply computes
the **Sun's altitude** for the current time and compares it to a configurable
threshold. The check happens within the ``gonet4.py`` script, therefore
it doesn't affect the cron scheduling and the script can still run at the same
times regardless of sunrise/sunset.

The sun gate is implemented in the new module ``utils/sun_gate.py`` and
``gonet4.py`` runs the sun gate when:

- a reliable GPS fix was acquired (``fix.ok``), and
- ``--sun-gate`` is passed on the command line.

The gate computes the Sun's altitude angle (degrees above the horizon)
using the `astral <https://astral.readthedocs.io/en/latest/>`_ library:

The gate is designed for remote deployment, so it intentionally fails open:
if anything unexpected occurs, imaging is allowed.

Examples include:

- GPS fix not available
- Astral computation failure
- unexpected runtime errors

In those cases the function returns ``True`` (image).

This guarantees that a software error cannot silently suppress
data acquisition.

In case the Sun gate is active and the Sun is above the threshold, the
function returns ``False`` (skip), and the script logs the decision and moves
on without capturing images. In addition, the script updates the status
marker to ``SunUp``, so that a clear status is available for monitoring.

.. flash_drive_copy:
Flash drive image copying
^^^^^^^^^^^^^^^^^^^^^^^^^

To simplify data retrieval and reduce SD card wear, the refactored system
supports **automatic copying of images to an external USB flash drive**.

This feature is enabled using:

.. code-block:: bash

   gonet4.py --flashdrive-copy

When enabled, the script performs the following steps after successful
post-processing:

1. Verify that a USB drive is mounted
2. Confirm the presence of a marker file identifying the drive as valid
3. Check that sufficient free space is available on the drive
4. Copy images to the flash drive
5. Verify the copy
6. Optionally delete the source file from the SD card

Only images **successfully processed during the current run** are considered for
migration.

Drive detection
"""""""""""""""

The system expects the flash drive to be mounted at:

.. code-block:: text

   /media/pi/usb

and to contain a marker file:

.. code-block:: text

   /media/pi/usb/.gonet_usb

This marker prevents accidental copying to unrelated removable devices.

Destination directory
"""""""""""""""""""""

Images are copied to:

.. code-block:: text

   /media/pi/usb/GONetDump/images

Safe copy procedure
"""""""""""""""""""

To ensure data integrity, each file transfer follows a safe sequence:

1. Copy the file to ``filename.jpg.part``
2. Verify the copy
3. Atomically rename ``.part`` to the final filename
4. Delete the source file (optional)

Verification methods include:

- sampled chunk hashing (default, fast)
- full SHA-256 hashing
- size-only verification (optional)

Fail-open behavior
""""""""""""""""""

If the USB drive is not present or not mounted:

- imaging proceeds normally
- no files are copied
- images remain on the SD card

This allows the system to operate normally even when the flash drive is removed
or replaced.

Speed considerations
"""""""""""""""""""

From benchmarks tests, we found that the average speed of copying and verifying a
GONet image (~18MB) is approximately 4.7-5.0 MB/s, which translates to about 4
seconds per image. Considering imaging runs on cronjob, keep in mind the extra
time taken for copying and verifying images to the flash drive when scheduling
runs.

.. USB_patch:
Patch for USB Flash Drive Auto-Mount and Formatting
===================================================

To support storing images on a flash drive, the repository provides a patch
that installs a small USB auto-mount system. 

This patch is implemented in the script::

    patches/patch_usb_mount.sh

This system ensures that **any inserted flash drive is mounted at a
predictable location** and thatthe imaging pipeline can write to it without
requiring manual intervention.

The patch also installs a convenience command that formats a flash drive with
the recommended filesystem and prepares the directory structure expected by
``gonet4.py``.

Context and Motivation
----------------------

Mounting USB drives on Linux systems can be surprisingly inconsistent, as
proven by the extensive testing and debugging process that led to the current
patch implementation. Several issues must be handled in order for the GONet
imaging pipeline to interact reliably with removable storage:

1. **Unpredictable mount locations**

   By default, removable drives may be mounted at paths such as::

       /media/pi/<LABEL>
       /run/media/pi/<LABEL>

   These locations depend on the drive label and the desktop environment.
   Since the camera runs in a headless environment without a graphical session,
   automatic mounting may not happen at all.

   The patch ensures that the flash drive is always mounted at::

       /media/pi/usb

   which provides a stable path that the imaging software can rely on.

2. **Filesystem permission issues**

   Most USB flash drives are formatted using FAT32, exFAT, or NTFS so that they
   are compatible with Windows and macOS. These filesystems **do not support
   traditional Unix ownership and permissions**.

   When mounted with default Linux settings, they often appear owned by ``root``::

       drwxr-xr-x root root /media/pi/usb

   In this case the user ``pi`` (which runs the camera software) cannot create
   files or directories on the drive, causing errors such as::

       PermissionError: [Errno 13] Permission denied

   The patch solves this by mounting the filesystem with explicit options::

       uid=pi,gid=pi,umask=0002

   This makes the filesystem appear writable by the ``pi`` user while preserving
   compatibility with non-Unix filesystems.

3. **Hot-plug support**

   The camera may remain powered while flash drives are inserted or removed.
   Without additional configuration, the system would not automatically mount a
   newly inserted device.

   The patch installs a **udev rule** that triggers a systemd service whenever a
   USB storage partition appears. This allows newly inserted drives to be
   mounted automatically without rebooting the camera.

   Such hot-plug support is not essential for the imaging pipeline, but it
   significantly improves usability.

Filesystem Choice
-----------------

The recommended filesystem for GONet flash drives is **exFAT**.

Reasons for choosing exFAT:

* Compatible with **Linux, Windows, and macOS**
* No 4 GB file size limit (unlike FAT32)
* Widely supported on modern operating systems
* Suitable for large image datasets

Although Linux filesystems such as ``ext4`` would provide better permission
handling and robustness, they cannot be read natively by Windows or macOS
systems, which makes them impractical for portable storage.

To simplify preparation of new flash drives, the patch installs the command::

    format-for-gonet

This command:

* identifies the inserted removable USB drive
* formats it as **exFAT**
* assigns a filesystem label
* creates the expected GONet directory structure

Installed Commands
------------------

The patch installs the following convenience commands:

``mount-usb``
    Mount the first detected removable USB drive at ``/media/pi/usb``.

``umount-usb``
    Safely unmount the USB drive after flushing pending writes.

``format-for-gonet``
    Erase and format the currently inserted USB drive as exFAT and create the
    directory structure required by the imaging pipeline.

Automatic Mounting at Startup
-----------------------------

We also configure the system to automatically mount a flash drive at startup
if one is already inserted. This is achieved through a **Systemd service**
that runs at boot and checks for the presence of a USB drive, mounting it if
found.

This is particularly useful for remote deployments, as it allows the freely
swap of flash drive while the camera is powered down, without requiring manual
mounting after each reboot.

.. boot_patch:
Boot Configuration Patch
===============================

The remote installation modifies the system boot behavior so that the camera
starts using the **remote** cron configuration instead of the default one.

This change is implemented by the script::

    patches/patch_remote_bootup.sh

The patch modifies the Raspberry Pi boot script::

    /etc/rc.local

A timestamped backup of the original file is created automatically before any
changes are applied.

The patch applies two modifications to to ``/etc/rc.local``.

Load remote cron configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Original boot behavior::

    su pi -c 'crontab /home/pi/Tools/Crontab/CronBackup.txt'

Patched behavior::

    su pi -c 'crontab /home/pi/Tools/Crontab/CronRemoteBackup.txt'

This ensures that the camera loads the **remote cron schedule** rather than
the default local configuration.

Update cron status marker
~~~~~~~~~~~~~~~~~~~~~~~~~

Original behavior::

    su pi -c 'touch /home/pi/Tools/Crontab/status/Default'

Patched behavior::

    su pi -c 'touch /home/pi/Tools/Crontab/status/RemoteDefault'

This status file indicates that the camera is operating in **remote cron
mode**.

.. extra:

Other files included in the repository
--------------------------------------

In addition to the refactored ``gonet4.py`` and the patches, the repository
includes the following files:

- ``webpages/remote_camera_index.php``: this is the simplified version of
    the camera control webpage, which is installed by the setup script. All
    unnecessary modes are removed, leaving only the **remote** mode, and the
    legacy **default** mode (i.e. 5 6s images every 5 minutes, no sun gate,
    no flash drive copy).
- ``cron/CronRemoteBackup.txt``: this is the cron configuration used in remote mode,
    which is installed by the setup script and loaded at boot by the boot patch.
