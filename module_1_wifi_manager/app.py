#!/usr/bin/env python3
"""
KaraokeZero - Module 1: WiFi Manager
Ultra-lightweight captive portal for headless Wi-Fi provisioning on Raspberry Pi Zero W.
Author: KaraokeZero Open-Source Project
License: MIT
"""

import os
import sys
import time
import logging
import threading
import subprocess
from typing import Dict, List, Optional, Any
from flask import Flask, render_template, request, jsonify

# Configure minimal, high-efficiency logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WiFiManager] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("WiFiManager")

app = Flask(__name__)

# In-memory state for non-blocking connection attempts
connection_lock = threading.Lock()
connection_state: Dict[str, Any] = {
    "status": "idle",       # idle, connecting, success, error
    "target_ssid": None,
    "message": "",
    "timestamp": 0
}


def parse_terse_line(line: str) -> List[str]:
    """
    Parses a single line of nmcli -t output.
    Colons ':' are field separators, and literal colons inside fields are escaped as '\\:'.
    """
    parts: List[str] = []
    current: List[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)
    parts.append(''.join(current))
    return parts


def run_nmcli_command(args: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    """
    Safely executes an nmcli command without shell=True.
    """
    cmd = ["nmcli"] + args
    logger.debug("Executing command: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False
    )


def get_current_wifi_status() -> Dict[str, Any]:
    """
    Retrieves current active Wi-Fi connection info and IP address.
    """
    status: Dict[str, Any] = {
        "connected": False,
        "ssid": None,
        "device": "wlan0",
        "ip_address": None,
        "signal": None
    }

    try:
        # Check active device status
        # Example format: DEVICE:TYPE:STATE:CONNECTION
        res = run_nmcli_command(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"], timeout=5)
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                if not line:
                    continue
                fields = parse_terse_line(line)
                if len(fields) >= 4:
                    dev, dev_type, state, conn = fields[0], fields[1], fields[2], fields[3]
                    if dev_type == "wifi" and state == "connected":
                        status["connected"] = True
                        status["ssid"] = conn
                        status["device"] = dev
                        break

        # Get IP address for wireless device
        dev_name = status["device"] or "wlan0"
        ip_res = run_nmcli_command(["-g", "IP4.ADDRESS", "dev", "show", dev_name], timeout=5)
        if ip_res.returncode == 0 and ip_res.stdout.strip():
            # ip_res may contain CIDR notation, e.g., "192.168.1.50/24"
            ip_raw = ip_res.stdout.strip().splitlines()[0]
            status["ip_address"] = ip_raw.split('/')[0]

        # Get signal strength if connected
        if status["connected"] and status["ssid"]:
            wifi_res = run_nmcli_command(["-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi", "list"], timeout=8)
            if wifi_res.returncode == 0:
                for line in wifi_res.stdout.strip().splitlines():
                    fields = parse_terse_line(line)
                    if len(fields) >= 3 and fields[0] == "*":
                        try:
                            status["signal"] = int(fields[2])
                        except ValueError:
                            pass
                        break

    except Exception as e:
        logger.warning("Error fetching Wi-Fi status: %s", e)

    return status


def scan_wifi_networks(rescan: bool = False) -> List[Dict[str, Any]]:
    """
    Scans for available Wi-Fi networks using nmcli.
    Deduplicates multiple BSSIDs for the same SSID, keeping the highest signal strength.
    """
    args = ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]
    if rescan:
        args.extend(["--rescan", "yes"])

    try:
        res = run_nmcli_command(args, timeout=20)
    except subprocess.TimeoutExpired:
        logger.error("Wi-Fi scan timed out.")
        return []
    except FileNotFoundError:
        logger.error("nmcli command not found on host system.")
        return []

    if res.returncode != 0:
        logger.error("nmcli scan failed: %s", res.stderr.strip())
        return []

    networks_map: Dict[str, Dict[str, Any]] = {}

    for line in res.stdout.strip().splitlines():
        if not line:
            continue
        fields = parse_terse_line(line)
        if len(fields) < 4:
            continue

        in_use, ssid, signal_str, security = fields[0], fields[1], fields[2], fields[3]

        # Ignore hidden/empty SSIDs
        ssid = ssid.strip()
        if not ssid or ssid == "--":
            continue

        try:
            signal = int(signal_str)
        except ValueError:
            signal = 0

        is_active = (in_use.strip() == "*")
        is_secured = bool(security.strip() and security.strip().upper() != "--")

        entry = {
            "ssid": ssid,
            "signal": signal,
            "security": security.strip() if is_secured else "Open",
            "is_secured": is_secured,
            "is_active": is_active
        }

        # Deduplicate: Keep highest signal or active connection
        if ssid not in networks_map:
            networks_map[ssid] = entry
        else:
            if is_active or (not networks_map[ssid]["is_active"] and signal > networks_map[ssid]["signal"]):
                networks_map[ssid] = entry

    # Sort: Active first, then descending by signal strength
    sorted_networks = sorted(
        networks_map.values(),
        key=lambda net: (1 if net["is_active"] else 0, net["signal"]),
        reverse=True
    )

    return sorted_networks


def _async_connect_worker(ssid: str, password: Optional[str]):
    """
    Background worker that connects to Wi-Fi and sets autoconnect priority to 50.
    Runs asynchronously to allow the HTTP response to be flushed before network migration.
    """
    global connection_state

    # Small pause to guarantee HTTP response delivery to client
    time.sleep(1.0)

    logger.info("Starting connection attempt to SSID: %s", ssid)

    try:
        connect_args = ["dev", "wifi", "connect", ssid]
        if password:
            connect_args.extend(["password", password])

        # Attempt connection (timeout 45s for DHCP lease & 4-way WPA handshake)
        res = run_nmcli_command(connect_args, timeout=45)

        with connection_lock:
            if res.returncode == 0:
                logger.info("Successfully connected to '%s'. Setting autoconnect priority to 50...", ssid)
                # Set autoconnect priority to 50 as specified in manifest logic_flow
                mod_res = run_nmcli_command([
                    "connection", "modify", ssid,
                    "connection.autoconnect-priority", "50",
                    "connection.autoconnect", "yes"
                ], timeout=10)

                if mod_res.returncode != 0:
                    logger.warning("Priority configuration warning: %s", mod_res.stderr.strip())

                connection_state["status"] = "success"
                connection_state["message"] = f"Successfully connected to '{ssid}'!"
            else:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed."
                logger.error("Failed to connect to '%s': %s", ssid, err_msg)
                connection_state["status"] = "error"
                connection_state["message"] = f"Connection error: {err_msg}"
            connection_state["timestamp"] = time.time()

    except Exception as e:
        logger.exception("Unexpected error during Wi-Fi connection: %s", e)
        with connection_lock:
            connection_state["status"] = "error"
            connection_state["message"] = f"Internal error: {str(e)}"
            connection_state["timestamp"] = time.time()


# ==========================================
# Routes & API Endpoints
# ==========================================

@app.route("/")
def index():
    """Renders the main mobile-friendly captive UI."""
    status = get_current_wifi_status()
    return render_template("index.html", current_status=status)


@app.route("/api/status", methods=["GET"])
def api_status():
    """Returns current connection status and IP address."""
    status = get_current_wifi_status()
    return jsonify({"success": True, "status": status})


@app.route("/api/scan", methods=["GET"])
def api_scan():
    """Scans and returns available Wi-Fi networks."""
    rescan = request.args.get("rescan", "true").lower() == "true"
    networks = scan_wifi_networks(rescan=rescan)
    return jsonify({
        "success": True,
        "count": len(networks),
        "networks": networks
    })


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """
    Initiates connection to the selected Wi-Fi network.
    Configures network with autoconnect-priority 50.
    """
    global connection_state

    data = request.get_json(silent=True) or request.form
    ssid = (data.get("ssid") or "").strip()
    password = (data.get("password") or "").strip()

    if not ssid:
        return jsonify({
            "success": False,
            "error": "Network SSID is required."
        }), 400

    with connection_lock:
        if connection_state["status"] == "connecting":
            return jsonify({
                "success": False,
                "error": "A connection attempt is already in progress. Please wait."
            }), 409

        connection_state["status"] = "connecting"
        connection_state["target_ssid"] = ssid
        connection_state["message"] = f"Attempting connection to '{ssid}'..."
        connection_state["timestamp"] = time.time()

    # Launch connection worker in background thread
    worker_thread = threading.Thread(
        target=_async_connect_worker,
        args=(ssid, password if password else None),
        daemon=True
    )
    worker_thread.start()

    return jsonify({
        "success": True,
        "message": f"Connection to '{ssid}' initiated.",
        "note": "Device is migrating networks. If connected via Admin Hotspot, reconnect to the venue Wi-Fi."
    })


@app.route("/api/connect/status", methods=["GET"])
def api_connect_status():
    """Checks the status of the ongoing or most recent connection attempt."""
    with connection_lock:
        return jsonify({
            "success": True,
            "state": connection_state
        })


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8888"))
    logger.info("Starting KaraokeZero WiFi Manager on %s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
