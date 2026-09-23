# KaraokeZero - Module 3: Installer & Provisioning Engine

The **Installer & Provisioning Engine** is the automated deployment system that turns a fresh **Raspberry Pi OS Lite (32-bit Bullseye)** image into an autonomous, ultra-low-overhead **KaraokeZero Appliance**.

---

## 1. Features & Architectural Principles

- **Dual Deployment Modes:**
  - **Unattended Mode:** If all settings in `config.env` are populated, the script runs non-interactively without user interruption (ideal for scripted or fleet deployments).
  - **Interactive Mode:** If any required configuration is missing, the script interactively guides the user through storage selection and network fallback configuration.
- **MicroSD Card Protection (Wear Leveling):**
  - Displays a prominent warning against running write-heavy operations on flash cards.
  - Formats `/etc/fstab` with `defaults,noatime,nofail,x-systemd.device-timeout=10` to ensure that an unplugged USB drive will not block system boot into recovery mode.
  - Automatically isolates SQLite databases, `yt-dlp` download buffers, and the media library to the external storage mount (`/mnt/external_hd/karaoke`).
- **Hardware & Firmware Tuning:**
  - Configures `gpu_mem=128` in `/boot/config.txt` for VideoCore IV MMAL video decoding.
  - Forces `hdmi_drive=2` so Mini-HDMI to VGA active adapters receive audio for their 3.5mm analog output.
  - Disables the blinking framebuffer console cursor via `consoleblank=0 vt.global_cursor_default=0` in `/boot/cmdline.txt`.
- **Integrated Systemd Mesh:**
  - Registers, links, and auto-starts `wifi_manager.service`, `pikaraoke.service`, and `orchestrator.service`.

---

## 2. Directory Structure

```
module_3_installer_script/
├── README.md               # Complete operational guide
├── config.env              # Base configuration (defaults with interactive prompts)
├── config.env.example      # Template with full sample values for unattended setup
├── install.sh              # Master provisioning bash script
├── pikaraoke.service       # Systemd unit template for PiKaraoke core
└── test_installer.sh       # Automated test suite (syntax, dry-run, mock input)
```

---

## 3. Quick Start & Usage

### 3.1. Interactive Installation (Default)
To run the interactive installer on a freshly booted Raspberry Pi:
```bash
cd module_3_installer_script
sudo bash install.sh
```

During execution, if `config.env` is missing required fields, the installer will:
1. Show the **Storage Warning Notice** and ask you to select between an external USB drive/SSD or internal SD card.
2. List all detected storage devices (`lsblk`) and let you specify the partition (e.g., `/dev/sda1`).
3. Prompt for your mobile phone's Wi-Fi hotspot SSID and password to register a Priority 100 fallback connection in NetworkManager.

### 3.2. Unattended / Headless Installation
Copy `config.env.example` to `config.env` and populate all fields:
```bash
cp config.env.example config.env
nano config.env
sudo bash install.sh
```
Because all required parameters are pre-filled, `install.sh` will complete the deployment without prompting.

### 3.3. Command Line Arguments
```bash
sudo bash install.sh [OPTIONS]

Options:
    --config <path>       Specify custom config file (default: config.env)
    --dry-run             Simulate installation without modifying the host system
    --non-interactive     Fail immediately if required variables are missing
    -h, --help            Show usage information
```

---

## 4. Configuration Variables (`config.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `STORAGE_TYPE` | `""` | Storage type: `external_hd` (recommended) or `sd_card`. |
| `STORAGE_DEVICE` | `""` | Partition path (e.g., `/dev/sda1`) or `UUID=...` for external storage. |
| `MOUNT_POINT` | `/mnt/external_hd/karaoke` | Mount path for the external drive in `/etc/fstab`. |
| `SD_CARD_STORAGE_PATH`| `""` | Local folder on SD card if `STORAGE_TYPE="sd_card"`. |
| `ADMIN_WIFI_SSID` | `""` | SSID of fallback network (Priority 100). |
| `ADMIN_WIFI_PASSWORD` | `""` | Password of fallback network. |
| `PIKARAOKE_PORT` | `5555` | Web interface port for PiKaraoke. |
| `WIFI_MANAGER_PORT` | `8888` | Web interface port for Module 1 Captive Portal. |
| `PIKARAOKE_REPO_URL` | `https://github.com/vicwomg/pikaraoke.git` | Upstream git repository. |
| `PIKARAOKE_BRANCH` | `master` | Git branch to clone. |
| `CONFIGURE_BOOT_CONFIG`| `true` | Apply `gpu_mem=128` and `hdmi_drive=2` in `/boot/config.txt`. |
| `SUPPRESS_FB_CURSOR` | `true` | Suppress console cursor via `/boot/cmdline.txt`. |
| `ENABLE_SERVICES_NOW` | `true` | Enable and start systemd services on installation completion. |

---

## 5. Verification & Automated Testing

Execute the test suite to validate syntax and simulated workflows:
```bash
bash test_installer.sh
```
```text
===================================================================
Running Module 3 Installer Test Suite
===================================================================
Running: Bash syntax check... PASSED
Running: CLI --help flag... PASSED
Running: Unattended dry run (config.env.example)... PASSED
Running: Non-interactive incomplete config check... PASSED
Running: Interactive external HD input simulation... PASSED
Running: Interactive internal SD card input simulation... PASSED
===================================================================
All tests passed successfully!
```
