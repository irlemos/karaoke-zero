# KaraokeZero - Display & Queue Orchestrator Daemon

The **Orchestrator Daemon** is the display and playback management engine for KaraokeZero, specifically engineered for resource-constrained, single-core embedded devices like the **Raspberry Pi Zero W** (512MB RAM, ARMv6) running **Raspberry Pi OS Lite** (32-bit Bookworm or newer, headless).

---

## 1. Problem Statement & Philosophy

Upstream PiKaraoke utilizes a web-based splash screen (`/splash`) that requires a modern web browser with HTML5 video and JavaScript support. On low-spec hardware:
- Launching Chromium in kiosk mode consumes **250MB–400MB of RAM** and saturates the single-core CPU at 100%, causing thermal throttling, audio underruns, and Out-Of-Memory (OOM) kernel panics.
- Running headless OS Lite means no X11 or Wayland display server is available.

**The Solution:**
Module 2 acts as a **Zero-GUI Hardware-Accelerated Display Client**. It monitors the PiKaraoke queue directly over local REST/WebSocket APIs and orchestrates video rendering straight to the display using **VLC CLI (`cvlc`)** with Direct Rendering Manager / Kernel Mode Setting hardware acceleration (`--vout drm`).

---

## 2. Hardware Topology & Media Routing

```
                     +---------------------------------------+
                     |         Raspberry Pi Zero W           |
                     |   PiKaraoke Core (--headless) :5555   |
                     |   Module 2 Orchestrator Daemon        |
                     +---------------------------------------+
                        |                                 |
                 USB 2.0 (OTG)                     Mini-HDMI Port
                        |                                 |
                        v                                 v
        +-------------------------------+     +-----------------------+
        | External USB Hard Drive       |     | Mini-HDMI to VGA      |
        | /mnt/external_hd/karaoke      |     | Active Adapter        |
        | - Persistent SQLite DB        |     +-----------------------+
        | - Song library / downloads    |         |               |
        +-------------------------------+      VGA Video       3.5mm P2 Audio
                                                  |            (GPU Passthrough)
                                                  v               |
                                           +-------------+        v
                                           | USB-Powered |    +----------------+
                                           | LED Monitor |    | External Multi-|
                                           | (Direct FB) |    | Channel Mixer  |
                                           +-------------+    +----------------+
                                                                  ^          |
                                                                  |          v
                                                            Microphones   Speakers
                                                            (Zero Lag)
```

1. **Video Decoding:** Direct rendering via Direct Rendering Manager / KMS (`--vout drm`), bypassing X11/Wayland completely.
2. **Audio Decoding:** Analog stereo sound extracted natively through the Mini-HDMI to VGA adapter's 3.5mm P2 jack, routed straight into the external analog mixer.
3. **Microphones:** Connected directly to the external mixer, completely isolated from software processing to guarantee **zero vocal latency**.

---

## 3. Finite State Machine (FSM) Lifecycle

```
       +-------------------------------------------------------+
       |                        BOOT                           |
       +-------------------------------------------------------+
                                  |
                                  v
       +-------------------------------------------------------+
       |                  DETECT_NETWORK_IP                    |
       |  - Identifies active IPv4 on wlan0                    |
       |  - Generates /tmp/qrcode.png via qrencode             |
       +-------------------------------------------------------+
                                  |
                                  v
+----->+-------------------------------------------------------+
|      |                      IDLE_STATE                       |
|      |  - cvlc loops idle_loop.mp4 on the framebuffer        |
|      |  - QR Code logo overlaid at bottom-right corner       |
|      |  - Polls GET /now_playing and listens for events      |
|      +-------------------------------------------------------+
|                                 |
|                                 | Track detected in queue
|                                 v
|      +-------------------------------------------------------+
|      |                   PREPARE_PLAYBACK                    |
|      |  - Terminates idle cvlc instance                      |
|      |  - Resolves /stream/<id>.mp4 media URL                |
|      +-------------------------------------------------------+
|                                 |
|                                 v
|      +-------------------------------------------------------+
|      |                     PLAYING_STATE                     |
|      |  - Spawns cvlc with --vout drm --play-and-exit        |
|      |  - Emits start_song to PiKaraoke                      |
|      |  - Syncs pause/resume state with mobile clients       |
|      +-------------------------------------------------------+
|                                 |
|                                 | Track ends (cvlc exits) OR Skip requested
|                                 v
|      +-------------------------------------------------------+
|      |                    FINALIZE_TRACK                     |
|      |  - Ensures process termination & releases GPU memory  |
|      |  - Emits end_song('complete') to advance the queue    |
+---------------------------------+
```

---

## 4. Components & File Breakdown

| File | Purpose |
| :--- | :--- |
| `orchestrator.py` | Main daemon entrypoint, CLI parser, signal handler, and FSM event loop. |
| `display_manager.py` | Subprocess manager for `cvlc` hardware decoding, OSD suppression, and logo overlay. |
| `network_watcher.py` | Detects network IP address and generates `/tmp/qrcode.png` via `qrencode`. |
| `pikaraoke_client.py` | Hybrid client interfacing with PiKaraoke via REST polling and real-time Socket.IO events. |
| `orchestrator.service` | Systemd service unit with strict memory (`64M`) and CPU (`25%`) limits. |
| `test_orchestrator.py` | Complete unit test suite verifying FSM transitions, argument building, and mocking. |

---

## 5. Embedded Constraints & Optimizations

- **Memory Footprint:** The Python daemon consumes ~**12MB–18MB RAM**. VLC uses ~**15MB–25MB RAM** during playback. Total appliance footprint stays well under 45MB RAM.
- **Process Recycling:** VLC processes are terminated and recreated between tracks, completely flushing memory buffers and preventing VideoCore IV handle leaks.
- **Zero Disk Wear:** Ephemeral assets (`/tmp/qrcode.png`, `/tmp/vlc_rc.sock`) reside in Linux `tmpfs` (RAM), preserving internal MicroSD card longevity.

---

## 6. Installation & Deployment

### Prerequisites
On Raspberry Pi OS Lite (Bullseye):
```bash
sudo apt update
sudo apt install -y vlc qrencode python3
```

### Running Manually:
```bash
python3 orchestrator.py --pikaraoke-url http://127.0.0.1:5555 --interface wlan0
```

### Command-Line Arguments:
| Argument | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `--pikaraoke-url` | `PIKARAOKE_URL` | `http://127.0.0.1:5555` | Base URL of local PiKaraoke server. |
| `--interface` | `NET_INTERFACE` | `wlan0` | Network interface to query for IP address. |
| `--port` | `PORT` | `5555` | PiKaraoke web port encoded into the QR code. |
| `--bg-video` | `BG_VIDEO` | `assets/idle_loop.mp4` | Path to custom idle background video file. |
| `--vout` | `VLC_VOUT` | `drm` | VLC video output engine (`drm` for RPi Bookworm DRM/KMS). |
| `--aout` | `VLC_AOUT` | `alsa` | VLC audio output plugin (`alsa`). |
| `--alsa-device` | `ALSA_DEVICE` | `default` | ALSA audio device name. |
| `--poll-interval` | `POLL_INTERVAL` | `1.0` | Status poll frequency in seconds. |
| `--no-rc` | - | `False` | Disable VLC remote control Unix socket. |

### Systemd Service Setup:
```bash
sudo cp ../systemd/orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable orchestrator.service
sudo systemctl start orchestrator.service
```

---

## 7. Running Tests

Execute the automated unit test suite:
```bash
python3 -m unittest discover -s . -p "test_*.py"
```
