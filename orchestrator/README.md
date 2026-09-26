# Display & Queue Orchestrator Daemon

The orchestrator daemon bridges the headless PiKaraoke backend and the physical video output. It is engineered specifically for resource-constrained systems such as the Raspberry Pi Zero W (ARMv6, single-core 1.0 GHz, 512 MB RAM) running Raspberry Pi OS Lite (32-bit Bookworm or newer).

---

## 1. Technical Context & Design Rationale

Upstream PiKaraoke ships with a web-based splash screen (`/splash`) that displays the current song title, upcoming queue entries, and connection instructions. In standard deployments, this interface runs inside a local web browser in kiosk mode.

On low-memory single-board computers, this approach is not practical:
- Modern web engines like Chromium consume between 250 MB and 400 MB of RAM in kiosk mode. On a 512 MB system, this leaves little headroom for the Linux kernel, Python services, and media decoding buffers, frequently triggering out-of-memory (OOM) kills.
- Sustained browser CPU utilization causes thermal throttling and frame drops on single-core ARMv6 processors.
- Minimal server distributions like Raspberry Pi OS Lite do not include X11 or Wayland display servers.

The orchestrator bypasses the browser entirely. It runs as a lightweight headless daemon that polls PiKaraoke's local API and coordinates video playback directly onto the display framebuffer via **VLC CLI (`cvlc`)** using Linux Direct Rendering Manager / Kernel Mode Setting hardware acceleration (`--vout drm`).

---

## 2. Hardware Topology & Media Routing

```
                     +---------------------------------------+
                     |         Raspberry Pi Zero W           |
                     |   PiKaraoke Core (--headless) :5555   |
                     |   Orchestrator Daemon                 |
                     +---------------------------------------+
                         |                                 |
                  USB 2.0 (OTG)                     Mini-HDMI Port
                         |                                 |
                         v                                 v
         +-------------------------------+     +-----------------------+
         | External Storage              |     | Mini-HDMI to VGA      |
         | /mnt/external_hd/karaoke      |     | Active Adapter        |
         | - SQLite persistent DB        |     +-----------------------+
         | - Song library / downloads    |         |               |
         +-------------------------------+      VGA Video       3.5mm Analog Audio
                                                   |            (GPU Passthrough)
                                                   v               |
                                            +-------------+        v
                                            | Monitor /   |    +----------------+
                                            | TV Screen   |    | External Multi-|
                                            | (Direct FB) |    | Channel Mixer  |
                                            +-------------+    +----------------+
                                                                   ^          |
                                                                   |          v
                                                             Microphones   Speakers
                                                             (Pure Analog)
```

1. **Video Decoding:** Direct rendering via Direct Rendering Manager (`--vout drm`), bypassing window managers and X11/Wayland layers.
2. **Audio Decoding:** Digital audio passes through HDMI to the active Mini-HDMI to VGA adapter. The adapter's built-in DAC outputs line-level stereo over a 3.5 mm jack directly into an external analog mixer.
3. **Microphone Isolation:** Microphones connect directly to the external mixer. Because vocal signals never enter the Raspberry Pi's software stack, there is zero processing latency.

---

## 3. Playback Lifecycle & State Machine

The orchestrator operates as a deterministic finite state machine (FSM):

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
|      |  - Loops background video via cvlc                    |
|      |  - Overlays QR code at bottom-right via logo filter   |
|      |  - Monitors GET /api/queue for upcoming tracks        |
|      +-------------------------------------------------------+
|                                 |
|                                 | Track present in queue
|                                 v
|      +-------------------------------------------------------+
|      |                   PREPARE_PLAYBACK                    |
|      |  - Terminates idle cvlc instance                      |
|      |  - Resolves media stream endpoint                     |
|      +-------------------------------------------------------+
|                                 |
|                                 v
|      +-------------------------------------------------------+
|      |                     PLAYING_STATE                     |
|      |  - Spawns cvlc with --vout drm --play-and-exit        |
|      |  - Signals track start to PiKaraoke                   |
|      |  - Synchronizes pause/skip commands with clients      |
|      +-------------------------------------------------------+
|                                 |
|                                 | Track finishes or user skips
|                                 v
|      +-------------------------------------------------------+
|      |                    FINALIZE_TRACK                     |
|      |  - Confirms process termination and frees GPU memory  |
|      |  - Emits end_song completion signal to advance queue  |
+---------------------------------+
```

---

## 4. Module Architecture

| Source File | Responsibility |
| :--- | :--- |
| `orchestrator.py` | Daemon entrypoint, command-line parsing, signal handling, and state machine loop. |
| `display_manager.py` | Manages the `cvlc` subprocess lifecycle, DRM arguments, OSD suppression, and logo overlay filters. |
| `network_watcher.py` | Resolves active IP addresses on the target interface and generates `/tmp/qrcode.png` using `qrencode`. |
| `pikaraoke_client.py` | Client interface handling both HTTP REST polling and WebSocket events against the local PiKaraoke server. |
| `test_orchestrator.py` | Unit test suite covering transition handling, subprocess argument generation, and mocking. |

---

## 5. Resource Management on Embedded Targets

- **Process Recycling:** Video decoders are prone to residual memory retention and handle leaks over long sessions. Rather than keeping a single player instance alive, the orchestrator cleanly terminates and restarts the `cvlc` process between tracks, ensuring memory allocations and GPU framebuffers are reset.
- **Volatile Storage (`tmpfs`):** Ephemeral files—such as dynamic QR codes (`/tmp/qrcode.png`) and the VLC control socket (`/tmp/vlc_rc.sock`)—are stored in RAM-backed temporary directories (`/tmp`). This prevents unnecessary flash write cycles on the host microSD card.
- **Memory Footprint:** The Python daemon typically uses between 12 MB and 18 MB of resident memory (RSS). VLC consumes between 15 MB and 25 MB during active playback. Total memory consumption across both components remains well below 45 MB.

---

## 6. Configuration & Deployment

### Manual Execution
For testing and development:

```bash
python3 orchestrator.py --pikaraoke-url http://127.0.0.1:5555 --interface wlan0
```

### CLI Parameters & Environment Variables

| Argument | Environment Variable | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `--pikaraoke-url` | `PIKARAOKE_URL` | `http://127.0.0.1:5555` | Base address of the local PiKaraoke service. |
| `--interface` | `NET_INTERFACE` | `wlan0` | Network interface to inspect for the active IP address. |
| `--port` | `PORT` | `5555` | Port number encoded into the attendee QR code. |
| `--bg-video` | `BG_VIDEO` | `assets/idle_loop.mp4` | Path to the looping background video file. |
| `--vout` | `VLC_VOUT` | `drm` | Video output module (`drm` for KMS/DRM framebuffer). |
| `--aout` | `VLC_AOUT` | `alsa` | Audio output module. |
| `--alsa-device` | `ALSA_DEVICE` | `default` | ALSA audio device identifier. |
| `--poll-interval` | `POLL_INTERVAL` | `1.0` | Queue polling interval in seconds. |
| `--no-rc` | - | `False` | Disables the VLC remote control Unix socket. |

### Systemd Service Management
The orchestrator is managed by systemd with explicit memory and CPU constraints:

```bash
sudo cp ../systemd/orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable orchestrator.service
sudo systemctl start orchestrator.service
```

Inspect service logs:
```bash
journalctl -u orchestrator.service -f
```

---

## 7. Running Tests

Run the test suite with Python's standard unittest runner:

```bash
python3 -m unittest discover -s . -p "test_*.py"
```
