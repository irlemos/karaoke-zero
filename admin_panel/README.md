# System Admin Panel

The **System Admin Panel** is the primary management and administration hub for KaraokeZero. Designed mobile-first for hosts and administrators, it runs a lightweight web application on port `8888` that manages network onboarding, YouTube song searching and background downloads, PiKaraoke operational settings, real-time hardware diagnostics, and device power controls.

The interface is completely self-contained (zero remote CDN dependencies) and works seamlessly offline.

---

## 1. Core Modules & Tab Architecture

The portal provides a fixed bottom navigation bar organized into 3 main tabs:

### Tab 1: Song Search & Background Downloads (`#tab-songs`)
- **YouTube Search:** Performs lightweight search queries against YouTube metadata via `yt-dlp` (`--flat-playlist --dump-json`) without requiring YouTube API keys or credentials.
- **Background Downloads:** Serialized background worker downloads songs directly to `/mnt/external_hd/karaoke/songs`. Downloads run independently without interrupting active video playback in PiKaraoke.
- **Audio & Video Quality Control:** Throttles video resolution to the configured setting (`bestvideo[height<=quality]`), while **always capturing the highest possible audio bitrate (`bestaudio`)**.
- **Live Queue Monitoring:** Real-time progress bars, speed, ETA, and state indicators (`queued`, `downloading`, `completed`, `error`).
- **PiKaraoke Catalog Rescan:** Instantly restarts `pikaraoke.service` to reindex the local catalog so newly downloaded tracks become immediately searchable for guests.

### Tab 2: System Settings & Power Management (`#tab-system`)
- **Guest Access Mode:**
  - **Online Mode:** Party guests can search and add YouTube songs directly from their smartphones on port `5555`.
  - **Offline Only Mode:** Locks YouTube search on PiKaraoke by setting `admin_password` in `config.ini`, restricting guests to sing only songs already saved on the local hard drive.
- **Default Video Quality:** Persistent setting (360p, 480p, 720p, 1080p) stored in `/mnt/external_hd/karaoke/data/system_settings.json` that survives reboots.
- **Hardware Telemetry:** Real-time readings of CPU temperature (color-coded thresholds), RAM usage, external drive free space, system uptime, and total local song count.
- **Safe Power Controls:** Dedicated buttons to cleanly reboot or power off the Raspberry Pi, complete with confirmation dialogs.

### Tab 3: Wi-Fi Management (`#tab-wifi`)
- **Current Status:** Displays connected SSID, IP address, wireless interface (`wlan0`), and signal strength.
- **Access Point Scanner:** Scans visible networks using NetworkManager (`nmcli`), automatically deduplicating mesh BSSIDs.
- **Venue Wi-Fi Provisioning:** Connects to the venue network with **Priority 50**, automatically saving credentials for future boot cycles.

---

## 2. Connection Lifecycle & Priority Model

KaraokeZero uses NetworkManager to handle network transitions using a two-tier priority model:

```
+-------------------------------------------------------------+
|                     SYSTEM STARTUP                          |
+-------------------------------------------------------------+
                               |
                               v
    +---------------------------------------------------+
    | NetworkManager scans for known wireless profiles: |
    | - Admin Fallback Hotspot:  Priority 100           |
    | - Venue Wi-Fi (Saved):     Priority 50            |
    +---------------------------------------------------+
                               |
         +---------------------+---------------------+
         | Venue network not found                   | Venue network reachable
         v                                           v
+-----------------------------+           +-----------------------------+
| Connects to Admin Hotspot   |           | Associates with Venue Wi-Fi |
| (Priority 100)              |           | (Priority 50)               |
+-----------------------------+           +-----------------------------+
         |                                           |
         v                                           v
+-----------------------------+           +-----------------------------+
| Administrator opens:        |           | PiKaraoke is accessible on  |
| http://<pi-ip>:8888         |           | the venue network IP        |
+-----------------------------+           +-----------------------------+
         |
         v
+-------------------------------------------------------+
| 1. Admin scans nearby networks in Wi-Fi tab           |
| 2. Submits venue credentials                          |
| 3. Service provisions connection with Priority 50     |
| 4. NetworkManager associates with the venue network   |
+-------------------------------------------------------+
```

---

## 3. HTTP API Reference

### System & Settings
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the mobile-first 3-tab administration panel. |
| `/api/status` | `GET` | Returns connection status, system diagnostics (CPU temp, RAM, storage, uptime), and active settings. |
| `/api/settings` | `GET` | Returns current persistent settings (`offline_mode`, `default_video_quality`, `audio_quality`). |
| `/api/settings` | `POST` | Updates persistent settings and synchronizes configuration with PiKaraoke. |
| `/api/system/reboot` | `POST` | Safely triggers an appliance reboot after returning HTTP confirmation. |
| `/api/system/shutdown` | `POST` | Safely powers off the appliance after returning HTTP confirmation. |

### Songs Search & Downloads
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/songs/search` | `GET` | Searches YouTube karaoke videos via `yt-dlp` metadata (`?q=<query>`). |
| `/api/songs/download` | `POST` | Enqueues a non-blocking background download task with selected video quality and best available audio. |
| `/api/songs/downloads` | `GET` | Returns active, queued, and recently completed download tasks with progress metrics. |
| `/api/pikaraoke/rescan` | `POST` | Refreshes the PiKaraoke catalog so newly downloaded songs appear immediately in search. |

### Wireless Networking
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/scan` | `GET` | Triggers a wireless scan via `nmcli`. Supports optional `?rescan=true` to force a hardware rescan. |
| `/api/connect` | `POST` | Dispatches an asynchronous connection worker for JSON payload: `{ "ssid": "...", "password": "..." }`. |
| `/api/connect/status` | `GET` | Returns the state of the background connection worker: `idle`, `connecting`, `success`, or `error`. |

---

## 4. Local Execution & Deployment

### Package Dependencies
On Debian or Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-flask network-manager yt-dlp python3-psutil
```

### Running Manually
For development and local testing:

```bash
python3 app.py
```

By default, the server binds to `0.0.0.0:8888`. Environment variables can override default network bindings:

```bash
PORT=8080 HOST=127.0.0.1 python3 app.py
```

### Running Unit Tests

```bash
python3 -m unittest discover -s . -p "test_*.py"
```

### Systemd Service Configuration
To run the Admin Panel as a persistent system service:

```bash
sudo cp ../systemd/admin_panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable admin_panel.service
sudo systemctl start admin_panel.service
```

Check status and operational logs:
```bash
journalctl -u admin_panel.service -f
```
