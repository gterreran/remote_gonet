# GONet Extensions for Remote Deployment

This repository contains extensions and refactorings of the original GONet camera
software, designed to support **remote deployment** and **unattended operation**.

## Table of Contents

- [Installation](#installation)
  - [Quick install](#quick-install)
  - [What the installer does](#what-the-installer-does)
- [File descriptions and refactoring details](#file-descriptions-and-refactoring-details)
  - [Refactoring of original `gonet4.py`](#refactoring-of-original-gonet4py)
  - [New features](#new-features)
    - [Multiple exposure times](#multiple-exposure-times)
    - [Sun gate (daylight skip) based on Sun altitude](#sun-gate-daylight-skip-based-on-sun-altitude)
    - [Flash drive image copying](#flash-drive-image-copying)
  - [Patch for USB Flash Drive Auto-Mount and Formatting](#patch-for-usb-flash-drive-auto-mount-and-formatting)
  - [Boot Configuration Patch](#boot-configuration-patch)
  - [Other files included in the repository](#other-files-included-in-the-repository)

## Installation

The remote GONet extensions can be installed directly on a camera using a
single bootstrap script. The installer downloads the required files from
GitHub and deploys them into the correct locations on the Raspberry Pi.

No manual cloning of the repository is required.

### Quick install

Run the following commands on the GONet camera:

```bash
curl -L -o setup_remote_gonet.sh \
    https://raw.githubusercontent.com/gterreran/remote_gonet/main/setup_remote_gonet.sh

chmod +x setup_remote_gonet.sh

sudo ./setup_remote_gonet.sh