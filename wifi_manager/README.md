# Wi-Fi Manager

The Wi-Fi Manager provides headless network onboarding for KaraokeZero. When operating single-board computers in changing environments—such as rental venues, parties, or friend's homes—reconfiguring network credentials without a keyboard and monitor attached is a common hurdle. 

This component runs a lightweight web service that allows any smartphone connected to the device to scan for local Wi-Fi networks and submit credentials.

---

## 1. Connection Lifecycle & Priority Model

KaraokeZero uses NetworkManager (`nmcli`) to handle network transitions using a two-tier priority model:

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
| 1. Web client fetches available SSIDs via:            |
|    nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi   |
| 2. User selects SSID and submits credentials          |
| 3. Service provisions connection with Priority 50     |
| 4. NetworkManager switches to the venue Wi-Fi         |
+-------------------------------------------------------+
```

### Connection Strategy
1. **Fallback Admin Hotspot (Priority 100):** If no recognized venue Wi-Fi is reachable, the device connects to an administrator's mobile hotspot. This ensures the appliance remains reachable for configuration anywhere.
2. **Venue Wi-Fi (Priority 50):** When credentials for the local venue network are submitted through the web UI, NetworkManager creates or updates a connection profile with priority 50.
3. **Seamless Migration:** Once the venue network connects, the device receives an IP address on the local network, allowing attendees to access PiKaraoke directly.

---

## 2. Design Considerations & Implementation Details

- **Zero Remote Dependencies:** The onboarding web interface contains no external CDN references. All styles and scripts are embedded directly into the HTML template. If the device connects to an access point with no active internet connection, the UI loads immediately without waiting for timed-out external asset requests.
- **Process Memory Footprint:** The web service is implemented with Flask and standard library modules, typically consuming between 15 MB and 20 MB of resident memory.
- **Safe Command Execution:** Network operations interact with `nmcli` via argument arrays with `shell=False`. This eliminates the risk of command injection vulnerabilities from crafted SSID or passphrase inputs.
- **BSSID Deduplication:** Venue environments often deploy multi-node mesh networks or range extenders broadcasting identical SSIDs. The parser aggregates duplicate SSIDs and presents only the entry with the strongest signal to simplify user selection.

---

## 3. HTTP API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the responsive network configuration web interface. |
| `/api/status` | `GET` | Returns active connection details: `{ "ssid": "...", "ip_address": "...", "device": "...", "signal": 85 }`. |
| `/api/scan` | `GET` | Triggers a wireless scan via `nmcli`. Supports optional `?rescan=true` to force a hardware rescan. |
| `/api/connect` | `POST` | Dispatches an asynchronous connection worker for JSON payload: `{ "ssid": "...", "password": "..." }`. |
| `/api/connect/status` | `GET` | Returns the state of the background connection worker: `idle`, `connecting`, `success`, or `error`. |

---

## 4. Local Execution & Deployment

### Package Dependencies
On Debian or Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-flask network-manager
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

### Systemd Service Configuration
To run the Wi-Fi Manager as a persistent system service:

```bash
sudo cp ../systemd/wifi_manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wifi_manager.service
sudo systemctl start wifi_manager.service
```

Check status and operational logs:
```bash
journalctl -u wifi_manager.service -f
```
