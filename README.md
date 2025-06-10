# Pterodactyl Backup Utility

## Overview

**Pterodactyl Backup Utility** is a Python-based tool designed to automate the backup and restoration of game servers managed by [Pterodactyl](https://pterodactyl.io/), leveraging **Proxmox Backup Server (PBS)** for storage. It supports scheduled backups using cron expressions, optional container shutdown during backups, and manual snapshot restoration.

> ⚠️ **Note:** This software is a work in progress and has only been tested on **Ubuntu 24.04**.  
> It should also work reliably on **Debian Bookworm (12)** or newer.



## Features

- 🔁 Automated backups based on cron schedules  
- 🛑 Optional container shutdown before backup  
- ✅ Container restart after backup (if it was running)  
- 💾 Backup to a Proxmox Backup Server (PBS)  
- 📤 Restore from specific PBS snapshots  
- 📋 List available snapshots for a given server  
- 📦 Logs all actions to both console and a file  



## Requirements

### System Requirements

- **Operating System:** Ubuntu 24.04 or Debian 12+ (Bookworm)
- **Python 3.10+** (default in Ubuntu 24.04)
- **Proxmox Backup Client**

> ⚠️ **Note:** The Proxmox Backup Client is **not officially supported on Ubuntu**, but has been tested and confirmed working on **Ubuntu 24.04**.  
> Earlier Ubuntu versions (e.g., 22.04 or 20.04) will likely fail due to dependency conflicts.



## Installing Dependencies

You can install the required Python dependencies either via `apt` or `pip`.

### Option 1: Using `apt` (recommended for system integration)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-yaml python3-apscheduler
```

### Option 2: Using `pip`

If using a virtual environment or installing manually:

```bash
pip3 install pyyaml apscheduler
```



## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/ThisIsTenou/pterodactyl-pbs-backups.git
cd pterodactyl-pbs-backups
```

### 2. Configuration

Copy and edit the example config file:

```bash
cp config-example.yaml config.yaml
nano config.yaml
```

Edit the configuration values to match your system setup.



## Usage

### Run Manually

Start the scheduler:

```bash
python3 pterodactyl-backups.py
```

### Manual Backup

```bash
python3 pterodactyl-backups.py --backup --server-id abc123
```

Optional force shutdown during backup:

```bash
python3 pterodactyl-backups.py --backup --server-id abc123 --shutdown
```

### List Snapshots

```bash
python3 pterodactyl-backups.py --list-snapshots --server-id abc123
```

### Restore Snapshot

```bash
python3 pterodactyl-backups.py --restore --server-id abc123 --snapshot snapshot-name
```



## Running as a `systemd` Service

To ensure the backup utility runs automatically on boot and keeps running in the background, you can set it up as a `systemd` service.

### 1. Create a Service File

Create the service file:

```bash
sudo nano /etc/systemd/system/pterodactyl-backups.service
```

Paste the following content:

```ini
[Unit]
Description=Pterodactyl Backup Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/pterodactyl-pbs-backups
ExecStart=/usr/bin/python3 /opt/pterodactyl-pbs-backups/pterodactyl-backups.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Make sure the paths in `WorkingDirectory` and `ExecStart` match your install location.

### 2. Enable and Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable pterodactyl-backups.service
sudo systemctl start pterodactyl-backups.service
```

### 3. Monitor the Service

Check service status:

```bash
sudo systemctl status pterodactyl-backups.service
```

View live logs:

```bash
journalctl -f -u pterodactyl-backups.service
```



## Logging

Logs are saved to:

```
logs/backup.log
```

Console output is also captured when running manually or via systemd.



## Limitations

- Only tested on **Ubuntu 24.04**
- Requires valid setup of Proxmox Backup Server credentials
- Earlier Ubuntu versions may not work due to library conflicts with PBS client



## Planned future Enhancements

- Log rotation
- Running service as docker container
- Adding the name variable as a comment to the backups

## Wishful thinking

- Integration into pterodactyl's webui
- Defining optional backup retention times within config (currently not implemented due to security risks of allowing for backup deletion from the client side)
