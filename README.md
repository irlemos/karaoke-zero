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
- **Hardware-Accelerated Video:** Video playback is rendered directly to the framebuffer via VLC's CLI (`cvlc`) utilizing GPU hardware decoding (`mmal_vout`).
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

## 🏗️ Architectural Modules

KaraokeZero is structured into three dedicated modular components:

### 1. `module_1_wifi_manager` (Captive Portal)
- Dynamic, ultra-lightweight Wi-Fi onboarding service built with Python and Flask.
- Interfaces directly with `NetworkManager` (`nmcli`) without desktop tools.
- Automatically connects to the Administrator's Mobile Hotspot (Priority `100`) if no venue Wi-Fi is reachable.
- Allows venue Wi-Fi selection via a lightweight, 100% offline captive mobile UI, configuring the network with Priority `50`.

### 2. `module_2_orchestrator_daemon` (Display & Queue Engine)
- Background daemon that polls the local PiKaraoke API (`/api/queue`).
- **Idle State:** Renders a looping background video overlaying a dynamically generated QR code (`qrencode`) directly on the screen pointing to the mobile web app (`http://<ip>:5555`).
- **Playing State:** Seamlessly switches to full-screen hardware-accelerated playback of the active song via `cvlc --vout mmal_vout`.
- Kills playback processes between tracks to prevent memory leaks and releases video buffers.

### 3. `module_3_installer_script` (One-Click Deployment)
- Automated provisioning script for fresh Raspberry Pi OS Lite installations.
- Configures `/etc/fstab` for the external USB drive, clones upstream PiKaraoke, and sets up systemd service units (`wifi_manager.service`, `orchestrator.service`, `pikaraoke.service`).

---

## 🚀 Quick Start & Deployment

To transform a fresh **Raspberry Pi OS Lite (32-bit Bullseye)** installation into the KaraokeZero appliance:

```bash
# 1. Clone the repository
git clone https://github.com/irlemos/karaoke-zero.git /tmp/karaoke-zero

# 2. Run the automated provisioning script
cd /tmp/karaoke-zero/module_3_installer_script
sudo bash install.sh

# 3. Reboot the Raspberry Pi to apply GPU and firmware tuning
sudo reboot
```

The interactive installer guides you through:
1. Reviewing the **MicroSD flash wear warning** and selecting your external USB drive/SSD (`/mnt/external_hd/karaoke`).
2. Registering your initial fallback Wi-Fi network (Admin Mobile Hotspot with Priority 100).
3. Automatically installing all dependencies, official `yt-dlp`, upstream PiKaraoke in a virtualenv, and enabling the systemd service mesh.

---

## 📋 Software Stack

| Layer | Component | Description |
| :--- | :--- | :--- |
| **Operating System** | Raspberry Pi OS Lite | 32-bit Bullseye (Legacy, headless, no desktop environment) |
| **Networking** | NetworkManager (`nmcli`) | Prioritized multi-profile connection management |
| **Karaoke Core** | [PiKaraoke](https://github.com/vicwomg/pikaraoke) | Headless daemon (`--headless --download-on-queue`) |
| **Media Player** | VLC CLI (`cvlc`) | Direct framebuffer rendering (`mmal_vout`) |
| **Display Tools** | `qrencode` | Generates mobile-access QR code on the fly |

---

## 🌐 Language & Contribution Standards

All source code, documentation, API payloads, UI templates, and commit messages in this repository must strictly adhere to **English (US)** as defined in [AGENTS.md](AGENTS.md) and [.agents/rules/project_guidelines.md](.agents/rules/project_guidelines.md).

---

## 📄 License

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See [LICENSE](LICENSE) for details.
