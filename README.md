# KaraokeZero

A dedicated, headless appliance wrapper for [PiKaraoke](https://github.com/vicwomg/pikaraoke) tailored for resource-constrained embedded systems, specifically single-core boards like the Raspberry Pi Zero W.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20Zero%20W%20%7C%203%20%7C%204-red.svg)](https://www.raspberrypi.com/)
[![OS](https://img.shields.io/badge/OS-Raspberry%20Pi%20OS%20Lite%20(32--bit)-lightgrey.svg)](https://www.raspberrypi.com/software/operating-systems/)

---

## Overview

Running a modern karaoke interface on minimal hardware presents distinct challenges. Upstream PiKaraoke includes a browser-based splash screen designed to display lyrics and QR codes on a connected monitor. On single-board computers with limited memory and processing power—such as the Raspberry Pi Zero W (1.0 GHz single-core ARMv6, 512 MB RAM)—running Chromium in kiosk mode consumes roughly 300 to 400 MB of RAM, leaving negligible headroom for Python processes, video decoders, and background services. This frequently leads to CPU saturation, thermal throttling, stuttering audio, and kernel out-of-memory (OOM) faults.

KaraokeZero solves this by decoupling the playback display from the browser environment. Operating entirely on Raspberry Pi OS Lite without X11 or Wayland, KaraokeZero functions as an appliance layer:

- **Direct DRM/KMS Video Playback:** Video is rendered directly to the Linux framebuffer using MPV (`mpv --vo=gpu --gpu-context=drm`), taking advantage of VideoCore hardware acceleration without desktop server overhead.
- **Zero-Latency Microphone Architecture:** Rather than processing microphone audio through the Linux sound subsystem—which introduces latency and consumes CPU cycles—vocal audio is kept in the analog domain. Audio from HDMI output is extracted via an HDMI-to-VGA adapter's 3.5 mm jack and routed into an external multichannel analog mixer alongside physical microphones.
- **Flash Storage Protection & Boot Guard:** Continuous disk writes quickly wear out microSD cards. KaraokeZero directs all write-intensive tasks (SQLite databases, temporary video download buffers from yt-dlp, and song files) to an external USB hard drive or SSD mounted at `/mnt/external_hd/karaoke`. If the external drive is absent, disconnected, or fails to mount at boot, startup is frozen on a dedicated warning screen in zero-write safe mode to guarantee that no phantom files or databases are created on the MicroSD card.
- **System Administration & Management Portal:** An onboard mobile-first management portal (`admin_panel`) running on port 8888 allows hosts to configure local Wi-Fi, search and download YouTube tracks in the background, toggle guest access modes (online vs. offline), customize download video quality, and manage device power safely.

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
1. **Video Decoding:** MPV runs via CLI (`mpv`) with `--vo=gpu --gpu-context=drm`, rendering frames directly to the display controller without a window manager or X11/Wayland overhead.
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
├── admin_panel/                # System management & administrative web portal
│   ├── app.py                  # Flask web service, yt-dlp worker, and NetworkManager API
│   ├── templates/index.html    # Mobile-first 3-tab web app (zero external CDN assets)
│   ├── test_admin_panel.py     # Unit tests for settings, downloads, and networking APIs
│   └── README.md               # Technical component documentation
│
├── orchestrator/               # Hardware display and queue synchronization daemon
│   ├── orchestrator.py         # Main loop and state machine coordinator
│   ├── display_manager.py      # Subprocess lifecycle manager for mpv
│   ├── screen_generator.py     # Generates high-contrast graphical idle details screen
│   ├── network_watcher.py      # IP resolution and dynamic QR code generation
│   ├── pikaraoke_client.py     # Local client for PiKaraoke REST & WebSocket APIs
│   ├── test_orchestrator.py    # Unit tests covering state transitions
│   └── README.md               # Technical component documentation
│
├── systemd/                    # Systemd service unit files
│   ├── pikaraoke.service       # Headless PiKaraoke daemon unit
│   ├── admin_panel.service     # System Admin Panel web service unit
│   └── orchestrator.service    # Display orchestrator daemon unit
│
└── tests/                      # Validation test suites
    └── test_installer.sh       # Installer syntax, input parsing, and dry-run tests
```

### 1. System Admin Panel (`admin_panel/`)
A lightweight, mobile-first Flask service running on port 8888 providing comprehensive management across 3 tabs:
- **Song Search & Background Downloads:** Search YouTube karaoke tracks via `yt-dlp` metadata, enqueue background downloads to `/mnt/external_hd/karaoke/songs` without disturbing playback, enforce video quality caps while capturing the best available audio bitrate (`bestaudio`), and trigger immediate PiKaraoke catalog rescanning.
- **System Settings & Power Controls:** Toggle PiKaraoke guest access (Online YouTube searching on port 5555 vs. Offline local-only songs), set default persistent download quality (360p to 1080p), monitor live hardware telemetry (CPU temp, RAM, storage, uptime), and initiate safe system reboot or poweroff with confirmation modals.
- **Headless Wi-Fi Provisioning:** Connects to venue networks with Priority 50, automatically falling back to an administrator's mobile hotspot with Priority 100 whenever no saved network is reachable.

### 2. Display Orchestrator (`orchestrator/`)
A Python service that monitors the local PiKaraoke queue (`/api/queue`) and drives the physical screen output via MPV:
- **Idle Mode:** When no tracks are queued, the orchestrator displays a graphical details screen rendered via `screen_generator.py` (or an optional looping background video). It renders the active IP, dynamic attendee connection QR code (`http://<ip>:5555`), and admin portal URL (`http://<ip>:8888`).
- **Active Playback:** When a user queues a track, the idle display transitions and the orchestrator launches `mpv` targeting the requested media stream using hardware GPU acceleration (`--vo=gpu --gpu-context=drm`) and direct ALSA HDMI audio.
- **Storage Validation & Boot Halt Safety:** On boot, if KaraokeZero was installed with external storage, the orchestrator verifies that the drive is present, mounted, and healthy. If the drive is missing, disconnected, or unreadable, the orchestrator halts boot, stops background services, and renders a high-contrast emergency warning screen via MPV DRM/KMS. The appliance remains frozen in safe mode without modifying any files until the user reconnects the drive or reboots. If data was lost, a new installation is required.
- **Process Recycling:** Between songs, the MPV process is terminated and cleanly re-spawned. This completely flushes memory allocations and releases VideoCore IV GPU handles, avoiding memory fragmentation during extended sessions.

### 3. Automated Installer (`install.sh`)
An unattended and interactive provisioning script intended for clean installations of Raspberry Pi OS Lite (32-bit Bookworm or newer). It manages package dependencies (`mpv`, `network-manager`, `yt-dlp`, `qrencode`, `python3-pil`), configures `/etc/fstab` for the external drive, builds isolated Python virtual environments under PEP 668, configures GPU memory allocations in `/boot/firmware/config.txt`, and enables the systemd service units.

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
| **Media Player** | MPV (`mpv`) | Direct Rendering Manager / KMS GPU acceleration (`--vo=gpu --gpu-context=drm`) |
| **QR Code Tool** | `qrencode` & Pillow | Generates dynamic connection QR images and graphical splash screens |
| **Admin Web Stack** | Python 3 / Flask / yt-dlp | Mobile-first 3-tab portal (8888) with zero external CDN dependencies |

---

## Testing & Validation

The repository includes test suites to verify installer integrity, parameter validation, administrative APIs, and orchestrator state machine logic:

```bash
# Run installer integration and syntax tests
bash tests/test_installer.sh

# Run admin panel unit tests
python3 -m unittest discover -s admin_panel

# Run orchestrator daemon unit tests
python3 -m unittest discover -s orchestrator
```

---

## Contributing & Development Standards

All source code, commit messages, API schemas, and documentation across this repository must follow **English (US)** as defined in [AGENTS.md](AGENTS.md). Pull requests and code additions should maintain headless compatibility and respect the 512 MB memory boundary of the Raspberry Pi Zero W.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See [LICENSE](LICENSE) for the full license text.
