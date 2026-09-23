# KaraokeZero - Module 1: WiFi Manager

Dynamic, ultra-lightweight captive portal for headless Wi-Fi network provisioning, optimized specifically for **Raspberry Pi Zero W** (512MB RAM, ARMv6).

---

## 1. Architecture & Network Flow

The `WiFi Manager` implements the network orchestration flow specified in `karaokezero-manifest.json`:

```
+-------------------------------------------------------------+
|                     RASPBERRY PI BOOT                       |
+-------------------------------------------------------------+
                              |
                              v
    +---------------------------------------------------+
    | NetworkManager searches for known connections.    |
    | - Admin Mobile Hotspot: Priority 100              |
    | - Venue Wi-Fi (registered): Priority 50           |
    +---------------------------------------------------+
                              |
        +---------------------+---------------------+
        | Venue Wi-Fi not found                     | Venue Wi-Fi available
        v                                           v
+-----------------------------+           +-----------------------------+
| Connects to Admin Hotspot   |           | Connects directly to Venue  |
| (Priority 100)              |           | Wi-Fi (Priority 50)         |
+-----------------------------+           +-----------------------------+
        |                                           |
        v                                           v
+-----------------------------+           +-----------------------------+
| User opens on smartphone:   |           | PiKaraoke is accessible on  |
| http://<pi-ip>:8888         |           | the local venue network IP  |
+-----------------------------+           +-----------------------------+
        |
        v
+-------------------------------------------------------+
| 1. Flask app scans networks via:                      |
|    nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi   |
| 2. User selects the Venue Wi-Fi and inputs password   |
| 3. App triggers connection and sets Priority 50       |
| 4. Pi automatically migrates to the venue's network   |
+-------------------------------------------------------+
```

---

## 2. Embedded & Low-Resource Features

- **Minimal Memory Footprint:** Built exclusively on Flask and the Python standard library. Typically consumes ~15–20MB of RAM.
- **100% Offline / Zero CDN Dependencies:** When connected to a local hotspot without active cellular data or external internet access, the web interface loads instantly without blocking on external CDN assets (no Google Fonts, Bootstrap CDN, etc.).
- **Security:** NetworkManager commands are executed using safe argument arrays (`shell=False`), eliminating any risk of command injection via SSID or password payloads.
- **BSSID Deduplication:** Automatically groups multiple APs broadcasting the same SSID (common in mesh/repeater venue networks) and retains the strongest signal entry.

---

## 3. API Endpoints

| Route | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Mobile-first web interface for smartphones. |
| `/api/status` | `GET` | Returns active connection state (`ssid`, `ip_address`, `device`, `signal`). |
| `/api/scan` | `GET` | Scans available Wi-Fi networks via `nmcli`. Supports `?rescan=true`. |
| `/api/connect` | `POST` | Initiates connection to `{ "ssid": "...", "password": "..." }` and sets autoconnect-priority 50. |
| `/api/connect/status` | `GET` | Polls the status of the background connection worker (`idle`, `connecting`, `success`, `error`). |

---

## 4. Local Execution & Testing

### Prerequisites
On Debian / Raspberry Pi OS Lite:
```bash
sudo apt update
sudo apt install -y python3-flask network-manager
```

### Running in Development:
```bash
python3 app.py
```
By default, the server binds to `http://0.0.0.0:8888`.
To customize the host or port:
```bash
PORT=8080 HOST=127.0.0.1 python3 app.py
```

### Systemd Service Deployment
Copy the provided unit file into systemd:
```bash
sudo cp wifi_manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wifi_manager.service
sudo systemctl start wifi_manager.service
```
