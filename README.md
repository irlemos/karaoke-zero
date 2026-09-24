# KaraokeZero 🎤⚡

> **The Headless, Ultra-Low Resource PiKaraoke Appliance**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20Zero%20W%20%7C%203%20%7C%204-red.svg)](https://www.raspberrypi.com/)
[![OS](https://img.shields.io/badge/OS-Raspberry%20Pi%20OS%20Lite%20(32--bit)-lightgrey.svg)](https://www.raspberrypi.com/software/operating-systems/)

KaraokeZero is an open-source appliance wrapper designed to run an ultra-low latency, headless karaoke station on highly constrained embedded hardware—specifically optimized for single-core, 512MB RAM devices like the **Raspberry Pi Zero W**.

Instead of forking [PiKaraoke](https://github.com/vicwomg/pikaraoke), KaraokeZero acts as a zero-overhead appliance layer that manages network provisioning, display orchestration directly on the Linux framebuffer, and hardware-accelerated video/audio routing.

---

## 🎯 Core Philosophy & Guarantees

- **Absolute Minimum Resource Consumption:** No X11/Wayland desktop environments and no local Chromium/browser instances on the Raspberry Pi.
- **Zero Audio Latency & Zero CPU Overhead:** Microphone processing completely bypasses the Pi's software audio stack via an external multichannel analog mixer.
- **Hardware-Accelerated Video:** Video playback is rendered directly to the screen via VLC's CLI (`cvlc`) utilizing KMS/DRM hardware acceleration (`--vout drm`).
- **SD Card Longevity (Wear Leveling Protection):** All write-heavy operations (SQLite database, yt-dlp download buffers, song storage) are routed to an external USB hard drive mounted at `/mnt/external_hd/karaoke`.

---

## 🔌 Hardware Topology

```
                     +---------------------------------------+
                     |         Raspberry Pi Zero W           |
                     |  (OS on Internal MicroSD Card)        |
                     +---------------------------------------+
                        |                                 |
                 USB 2.0 (OTG)                     Mini-HDMI Port
                        |                                 |
                        v                                 v
        +-------------------------------+     +-----------------------+
        | External USB Hard Drive       |     | Mini-HDMI to VGA      |
        | /mnt/external_hd/karaoke      |     | Active Adapter        |
        | - Persistent SQLite DB        |     +-----------------------+
        | - Songs library               |         |               |
        | - yt-dlp download buffer      |      VGA Video       3.5mm P2 Audio
        +-------------------------------+         |            (GPU Passthrough)
                                                  v               |
                                           +-------------+        v
                                           | USB-Powered |    +----------------+
                                           | LED Monitor |    | External Multi-|
                                           +-------------+    | Channel Mixer  |
                                                              +----------------+
                                                                  ^          |
                                                                  |          v
                                                            Microphones   Speakers
                                                            (Zero Lag)
```

---

## 📁 Repository Structure

```text
karaoke-zero/
├── install.sh                  # Root automated deployment script
├── config.env                  # Deployment configuration file
├── config.env.example          # Sample configuration for unattended setups
├── karaokezero-manifest.json   # Architecture manifest v2.0.0
├── AGENTS.md                   # Project design guidelines and constraints
├── README.md                   # Project overview and deployment guide
├── LICENSE                     # AGPL-3.0 License
│
├── wifi_manager/               # Captive-style portal for Wi-Fi management
│   ├── app.py                  # Flask web service interacting with nmcli
│   ├── templates/index.html    # Standalone mobile UI (zero external CDNs)
│   ├── test_wifi_manager.py    # Unit tests for network parser and endpoints
│   └── README.md               # Technical component documentation
│
├── orchestrator/               # Hardware-accelerated playback and queue engine
│   ├── orchestrator.py         # Main daemon entrypoint and state machine
│   ├── display_manager.py      # Subprocess manager for cvlc (--vout drm)
│   ├── network_watcher.py      # Generates dynamic QR code for web access
│   ├── pikaraoke_client.py     # Local REST & WebSocket client for PiKaraoke
│   ├── test_orchestrator.py    # Unit test suite for display and transitions
│   └── README.md               # Technical component documentation
│
├── systemd/                    # Systemd service unit templates
│   ├── pikaraoke.service       # PiKaraoke core headless daemon service
│   ├── wifi_manager.service    # Captive portal service unit
│   └── orchestrator.service    # Display orchestrator service unit
│
└── tests/                      # Automated test suite
    └── test_installer.sh       # Comprehensive installer integration tests
```

---

## 🏗️ System Components

### 1. `wifi_manager/` (Captive Portal)
- Dynamic, ultra-lightweight Wi-Fi onboarding service built with Python and Flask.
- Interfaces directly with `NetworkManager` (`nmcli`) without desktop tools.
- Automatically connects to the Administrator's Mobile Hotspot (Priority `100`) if no venue Wi-Fi is reachable.
- Allows venue Wi-Fi selection via a lightweight, 100% offline captive mobile UI, configuring the network with Priority `50`.

### 2. `orchestrator/` (Display & Queue Engine)
- Background daemon that polls the local PiKaraoke API (`/api/queue`).
- **Idle State:** Renders a looping background video overlaying a dynamically generated QR code (`qrencode`) directly on the screen pointing to the mobile web app (`http://<ip>:5555`).
- **Playing State:** Seamlessly switches to full-screen hardware-accelerated playback of the active song via `cvlc --vout drm`.
- Kills playback processes between tracks to prevent memory leaks and releases video buffers.

### 3. `install.sh` (Master Provisioning Engine)
- Automated deployment script located at the repository root for fresh Raspberry Pi OS Lite installations.
- Configures `/etc/fstab` for the external USB drive, clones latest upstream PiKaraoke (from `master`), sets up Python virtual environments (PEP 668), and enables all systemd services.

---

## 🚀 Quick Start & Deployment

To transform a fresh **Raspberry Pi OS Lite (32-bit Bookworm or newer)** installation into the KaraokeZero appliance:

### 1. Bootstrap Prerequisites
Clean minimal installations of Raspberry Pi OS Lite do not ship with `git` or `curl`. Install them first:
```bash
sudo apt update && sudo apt install -y git curl
```

### 2. Run Automated Provisioning
```bash
# Clone the repository
git clone https://github.com/irlemos/karaoke-zero.git /tmp/karaoke-zero
cd /tmp/karaoke-zero

# Run the installer script directly from the repository root
sudo bash install.sh

# Reboot the Raspberry Pi to apply GPU memory & firmware tuning
sudo reboot
```

### 3. Installer Command-Line Arguments
```bash
sudo bash install.sh [OPTIONS]

Options:
    --config <path>       Specify custom config file (default: config.env)
    --log <path>          Specify custom log file (default: install.log)
    --dry-run             Simulate installation without modifying the host system
    --non-interactive     Fail immediately if required variables are missing
    -h, --help            Show usage information
```

### 4. Logging & Diagnostics
The installer records all terminal output (stdout and stderr) to a clean, fresh log file on every run:
```bash
cat install.log
```

---

## 📋 Software Stack

| Layer | Component | Description |
| :--- | :--- | :--- |
| **Operating System** | Raspberry Pi OS Lite | 32-bit Bookworm or newer (headless, no desktop environment, Python 3.11+) |
| **Networking** | NetworkManager (`nmcli`) | Prioritized multi-profile connection management |
| **Karaoke Core** | [PiKaraoke](https://github.com/vicwomg/pikaraoke) | Headless daemon (`--headless --download-path`) |
| **Media Player** | VLC CLI (`cvlc`) | Direct Rendering Manager / KMS (`--vout drm`) |
| **Display Tools** | `qrencode` | Generates mobile-access QR code on the fly |

---

## 🧪 Automated Testing

Execute the test suites to validate installer integrity and component state machines:
```bash
# Run installer test suite (dry-run, syntax, logging, input simulations)
bash tests/test_installer.sh

# Run orchestrator daemon unit tests
python3 -m unittest discover -s orchestrator
```

---

## 🌐 Language & Contribution Standards

All source code, documentation, API payloads, UI templates, and commit messages in this repository must strictly adhere to **English (US)** as defined in [AGENTS.md](AGENTS.md) and [.agents/rules/project_guidelines.md](.agents/rules/project_guidelines.md).

---

## 📄 License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See [LICENSE](LICENSE) for details.
