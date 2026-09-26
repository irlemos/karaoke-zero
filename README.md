# KaraokeZero

A dedicated, headless appliance wrapper for [PiKaraoke](https://github.com/vicwomg/pikaraoke) tailored for resource-constrained embedded systems, specifically single-core boards like the Raspberry Pi Zero W.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20Zero%20W%20%7C%203%20%7C%204-red.svg)](https://www.raspberrypi.com/)
[![OS](https://img.shields.io/badge/OS-Raspberry%20Pi%20OS%20Lite%20(32--bit)-lightgrey.svg)](https://www.raspberrypi.com/software/operating-systems/)

---

## Overview

Running a modern karaoke interface on minimal hardware presents distinct challenges. Upstream PiKaraoke includes a browser-based splash screen designed to display lyrics and QR codes on a connected monitor. On single-board computers with limited memory and processing power—such as the Raspberry Pi Zero W (1.0 GHz single-core ARMv6, 512 MB RAM)—running Chromium in kiosk mode consumes roughly 300 to 400 MB of RAM, leaving negligible headroom for Python processes, video decoders, and background services. This frequently leads to CPU saturation, thermal throttling, stuttering audio, and kernel out-of-memory (OOM) faults.

KaraokeZero solves this by decoupling the playback display from the browser environment. Operating entirely on Raspberry Pi OS Lite without X11 or Wayland, KaraokeZero functions as an appliance layer:

- **Direct DRM/KMS Video Playback:** Video is rendered directly to the Linux framebuffer using VLC's Direct Rendering Manager interface (`cvlc --vout drm`), taking advantage of VideoCore hardware acceleration without desktop server overhead.
- **Zero-Latency Microphone Architecture:** Rather than processing microphone audio through the Linux sound subsystem—which introduces latency and consumes CPU cycles—vocal audio is kept in the analog domain. Audio from HDMI output is extracted via an HDMI-to-VGA adapter's 3.5 mm jack and routed into an external multichannel analog mixer alongside physical microphones.
- **Flash Storage Protection:** Continuous disk writes quickly wear out microSD cards. KaraokeZero directs all write-intensive tasks (SQLite databases, temporary video download buffers from yt-dlp, and song files) to an external USB hard drive or SSD mounted at `/mnt/external_hd/karaoke`.
- **Headless Network Provisioning:** When moving between home networks, venues, or outdoor gatherings, an onboard captive web portal (`wifi_manager`) allows attendees or hosts to configure local Wi-Fi from any smartphone browser without requiring an attached keyboard or monitor.

---

## Hardware Architecture & Media Path

```
                     +---------------------------------------+
                     |         Raspberry Pi Zero W           |
                     |     (OS on MicroSD / tmpfs RAM)       |
                     +---------------------------------------+
                         |                                 |
                  USB 2.0 (OTG)                     Mini-HDMI Port
                         |                                 |
                         v                                 v
         +-------------------------------+     +-----------------------+
         | External Storage              |     | Mini-HDMI to VGA      |
         | /mnt/external_hd/karaoke      |     | Active Adapter        |
         | - SQLite persistent DB        |     +-----------------------+
         | - Song library                |         |               |
         | - yt-dlp download cache       |      VGA Video       3.5mm Analog Audio
         +-------------------------------+         |            (GPU Passthrough)
                                                   v               |
                                            +-------------+        v
                                            | Monitor /   |    +----------------+
                                            | TV Screen   |    | External Multi-|
                                            +-------------+    | Channel Mixer  |
                                                               +----------------+
                                                                   ^          |
                                                                   |          v
                                                             Microphones   PA / Speakers
                                                             (Pure Analog)
```

### Media Flow Breakdown
1. **Video Decoding:** VLC runs via CLI (`cvlc`) with `--vout drm --no-osd`, rendering frames directly to the display controller without a window manager.
2. **Audio Extraction:** Stereo track audio travels digitally over HDMI to an active Mini-HDMI to VGA adapter, which exposes a 3.5 mm analog stereo jack. This signal feeds an external mixer channel.
3. **Vocal Isolation:** Microphones connect directly into dedicated mixer channels with hardware gain and echo controls. The Raspberry Pi never captures or processes vocal streams, completely eliminating software audio latency.

---

## System Architecture

KaraokeZero coordinates three background daemons managed by systemd:

```text
karaoke-zero/
├── install.sh                  # Host provisioning script for Raspberry Pi OS Lite
├── config.env                  # Deployment parameters (mount paths, default SSID)
├── config.env.example          # Sample template for unattended installations
├── karaokezero-manifest.json   # Architectural blueprint and hardware specs
├── AGENTS.md                   # Repository coding and language rules
├── README.md                   # Main documentation
├── LICENSE                     # AGPL-3.0 License
│
├── wifi_manager/               # Captive network onboarding service
│   ├── app.py                  # Flask web service wrapping NetworkManager (nmcli)
│   ├── templates/index.html    # Self-contained mobile UI (zero external assets)
│   ├── test_wifi_manager.py    # Unit tests for parser and API endpoints
│   └── README.md               # Technical component documentation
│
├── orchestrator/               # Hardware display and queue synchronization daemon
│   ├── orchestrator.py         # Main loop and state machine coordinator
│   ├── display_manager.py      # Subprocess lifecycle manager for cvlc
│   ├── network_watcher.py      # IP resolution and dynamic QR code generation
│   ├── pikaraoke_client.py     # Local client for PiKaraoke REST & WebSocket APIs
│   ├── test_orchestrator.py    # Unit tests covering state transitions
│   └── README.md               # Technical component documentation
│
├── systemd/                    # Systemd service unit files
│   ├── pikaraoke.service       # Headless PiKaraoke daemon unit
│   ├── wifi_manager.service    # Captive portal web service unit
│   └── orchestrator.service    # Display orchestrator daemon unit
│
└── tests/                      # Validation test suites
    └── test_installer.sh       # Installer syntax, input parsing, and dry-run tests
```

### 1. Wi-Fi Manager (`wifi_manager/`)
A lightweight Flask service running on port 8888. It interacts with `NetworkManager` via `nmcli` to scan for wireless access points, deduplicate BSSIDs across mesh systems, and establish connections.
- **Priority 100 (Fallback Hotspot):** The Pi is configured to automatically connect to an administrator's mobile hotspot when no recognized venue network is found.
- **Priority 50 (Venue Wi-Fi):** When configured via the web UI, local venue networks are assigned priority 50. NetworkManager will favor the venue connection once established.
- **Self-Contained Interface:** The mobile HTML/CSS interface contains zero external CDN dependencies (no remote web fonts, frameworks, or icons), allowing it to load instantly on devices connected to the Pi before internet routing is established.

### 2. Display Orchestrator (`orchestrator/`)
A Python service that monitors the local PiKaraoke queue (`/api/queue`) and drives the physical screen output:
- **Idle Mode:** When no tracks are queued, the orchestrator plays a looping background animation (`assets/idle_loop.mp4`). It periodically queries `network_watcher.py` for the current IP on the active network interface (`wlan0`), generates a QR code via `qrencode` targeting `http://<ip>:5555`, and overlays the graphic on the video stream using VLC's logo sub-source filter.
- **Active Playback:** When a user queues a track, the idle loop terminates and the orchestrator launches `cvlc` targeting the requested media stream. 
- **Process Recycling:** Between songs, the VLC process is terminated and re-spawned. This completely flushes memory allocations and releases VideoCore IV GPU handles, avoiding memory fragmentation during extended sessions.

### 3. Automated Installer (`install.sh`)
An unattended and interactive provisioning script intended for clean installations of Raspberry Pi OS Lite (32-bit Bookworm or newer). It manages package dependencies, configures `/etc/fstab` for the external drive, builds isolated Python virtual environments under PEP 668, configures GPU memory allocations in `/boot/firmware/config.txt`, and enables the systemd service units.

---

## Installation & Setup

### Prerequisites
Raspberry Pi OS Lite images are intentionally minimal and omit version control tools. Ensure `git` and `curl` are present:

```bash
sudo apt update && sudo apt install -y git curl
```

### Running the Installer
Clone the repository and run the provisioning script with root privileges:

```bash
git clone https://github.com/irlemos/karaoke-zero.git /tmp/karaoke-zero
cd /tmp/karaoke-zero

# Launch interactive installation
sudo bash install.sh

# Reboot to apply GPU memory splits and hardware configuration
sudo reboot
```

### Installer CLI Arguments
For automated setups, parameters can be passed directly via command-line flags or an environment file:

```bash
sudo bash install.sh [OPTIONS]

Options:
    --config <path>       Path to custom configuration file (default: config.env)
    --log <path>          Path to execution log file (default: install.log)
    --dry-run             Simulate installation without modifying the host system
    --non-interactive     Fail immediately if required variables are missing from config
    -h, --help            Display help and option summary
```

### Diagnostic Logs
The installer records all standard output and error streams to `install.log` in the working directory:

```bash
cat install.log
```

---

## Software Stack

| Layer | Component | Implementation Details |
| :--- | :--- | :--- |
| **Operating System** | Raspberry Pi OS Lite | 32-bit Bookworm or newer (headless, systemd, Linux 6.x) |
| **Network Engine** | NetworkManager (`nmcli`) | Managed multi-profile connection priorities and AP scanning |
| **Karaoke Core** | [PiKaraoke](https://github.com/vicwomg/pikaraoke) | Headless daemon (`--headless --download-path`) |
| **Media Player** | VLC (`cvlc`) | Direct Rendering Manager / KMS acceleration (`--vout drm`) |
| **QR Code Tool** | `qrencode` | Generates dynamic connection QR images in `tmpfs` |
| **Portal Web Stack** | Python 3 / Flask | Lightweight HTTP service without external runtime dependencies |

---

## Testing & Validation

The repository includes test suites to verify installer integrity, parameter validation, and orchestrator state machine logic:

```bash
# Run installer integration and syntax tests
bash tests/test_installer.sh

# Run orchestrator daemon unit tests
python3 -m unittest discover -s orchestrator
```

---

## Contributing & Development Standards

All source code, commit messages, API schemas, and documentation across this repository must follow **English (US)** as defined in [AGENTS.md](AGENTS.md). Pull requests and code additions should maintain headless compatibility and respect the 512 MB memory boundary of the Raspberry Pi Zero W.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See [LICENSE](LICENSE) for the full license text.
