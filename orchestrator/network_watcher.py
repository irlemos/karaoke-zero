#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Network Watcher & QR Code Generator

Detects network IP changes and dynamically generates mobile access QR codes
using qrencode for the idle display overlay.
"""

import logging
import os
import shutil
import socket
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger("Orchestrator.NetworkWatcher")


class NetworkWatcher:
    """
    Monitors active network IP address and renders access QR code.
    """

    def __init__(
        self,
        interface: str = "wlan0",
        port: int = 5555,
        qr_output_path: str = "/tmp/qrcode.png",
        base_url_override: Optional[str] = None
    ):
        self.interface = interface
        self.port = port
        self.qr_output_path = qr_output_path
        self.base_url_override = base_url_override
        self.current_ip: Optional[str] = None
        self.current_url: Optional[str] = None

    def get_ip_address(self) -> Optional[str]:
        """
        Retrieves the IPv4 address for the configured interface or default gateway.
        Uses non-blocking local socket inspection without sending actual packets.
        """
        if self.base_url_override:
            return "override"

        # Try to resolve IP via active socket connection probe (reliable across Linux distros)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # 8.8.8.8 does not need to be reachable; the OS selects the default egress interface
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            s.close()

        # Fallback: Parse `ip -4 addr show <interface>` or `hostname -I`
        try:
            cmd = ["ip", "-4", "addr", "show", self.interface]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("inet "):
                        # e.g., "inet 192.168.1.100/24 brd ..."
                        parts = line.split()
                        if len(parts) >= 2:
                            return parts[1].split("/")[0]
        except Exception as e:
            logger.debug("Failed to inspect %s via ip tool: %s", self.interface, e)

        # Secondary fallback: `hostname -I`
        try:
            res = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                ips = res.stdout.strip().split()
                for candidate in ips:
                    if not candidate.startswith("127."):
                        return candidate
        except Exception:
            pass

        return None

    def get_access_url(self) -> Optional[str]:
        """Returns the web access URL formatted as http://<ip>:<port>."""
        if self.base_url_override:
            return self.base_url_override
        ip = self.get_ip_address()
        if ip:
            return f"http://{ip}:{self.port}"
        return None

    def generate_qr_code(self, url: str) -> bool:
        """
        Invokes qrencode to render a high-contrast PNG QR code.
        """
        if not shutil.which("qrencode"):
            logger.warning("qrencode utility not found in PATH. QR code overlay unavailable.")
            return False

        try:
            # -s 6: block size 6 pixels
            # -m 2: margin 2 modules (compact)
            cmd = [
                "qrencode",
                "-s", "6",
                "-m", "2",
                "-o", self.qr_output_path,
                url
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and os.path.exists(self.qr_output_path):
                logger.info("Generated QR code for '%s' -> %s", url, self.qr_output_path)
                return True
            else:
                logger.error("qrencode failed: %s", res.stderr.strip())
                return False
        except Exception as e:
            logger.exception("Error executing qrencode: %s", e)
            return False

    def get_terminal_qr(self, url: Optional[str] = None) -> str:
        """
        Renders an ANSI UTF-8 block QR code for display directly on the Linux console.
        Uses qrencode -t UTF8 if available, or python qrcode as fallback.
        """
        target_url = url or self.current_url or self.get_access_url()
        if not target_url:
            return ""

        if shutil.which("qrencode"):
            try:
                cmd = ["qrencode", "-t", "UTF8", "-m", "1", target_url]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception as e:
                logger.debug("Failed to render terminal QR with qrencode: %s", e)

        try:
            import io
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(target_url)
            qr.make(fit=True)
            output = io.StringIO()
            qr.print_ascii(out=output, invert=True)
            return output.getvalue().strip()
        except Exception:
            pass

        return ""

    def update(self) -> Tuple[bool, Optional[str]]:
        """
        Checks for IP address or URL changes.
        If changed, regenerates the QR code.
        Returns (has_changed, access_url).
        """
        url = self.get_access_url()
        if not url:
            if self.current_url is not None:
                self.current_url = None
                self.current_ip = None
                return True, None
            return False, None

        if url != self.current_url or not os.path.exists(self.qr_output_path):
            logger.info("Network URL changed or QR missing: %s (was: %s)", url, self.current_url)
            self.current_url = url
            self.current_ip = self.get_ip_address()
            success = self.generate_qr_code(url)
            return success, url

        return False, url
