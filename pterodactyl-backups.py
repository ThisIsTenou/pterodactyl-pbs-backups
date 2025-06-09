# Import required libraries
import yaml                                                     # For parsing YAML configuration files
import subprocess                                               # For running system commands
import os                                                       # For file and path operations
import logging                                                  # For application logging
from apscheduler.schedulers.blocking import BlockingScheduler   # For scheduling jobs
from apscheduler.triggers.cron import CronTrigger               # For cron-style scheduling
from datetime import datetime                                   # For timestamp operations
import sys                                                      # For system operations
from pathlib import Path                                        # For path operations
import glob                                                     # For file pattern matching
import shutil                                                   # For file operations
import argparse                                                # For command-line argument parsing

# Configure logging with both console and file output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),         # Log to console
        logging.FileHandler('logs/backup.log')          # Log to file
    ]
)
logger = logging.getLogger(__name__)

# Define constants
CONFIG_PATH = "config.yaml"                                                 # Path to configuration file

def load_config():
    """
    Load and validate the configuration file.
    Returns the config dict if valid, exits if invalid.
    """
    try:
        config_path = Path(CONFIG_PATH)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
            
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
            
        # Validate config structure
        if not isinstance(config.get('servers'), dict):
            raise ValueError("Config must contain a 'servers' dictionary")
            
        # Validate required settings for each server
        for server_id, settings in config['servers'].items():
            if 'schedule' not in settings:
                raise ValueError(f"Server {server_id} missing required 'schedule' setting")
            if 'name' not in settings:
                raise ValueError(f"Server {server_id} missing required 'name' setting")
            
        return config
    except (yaml.YAMLError, FileNotFoundError, ValueError) as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

# Load settings from config
config = load_config()
VOLUMES_PATH = config['settings']['volumes_path']                           # Path to Docker volumes
PBS_REPOSITORY = config['settings']['pbs_repository']                       # Proxmox Backup Server datasource
PBS_NAMESPACE = config['settings']['pbs_namespace']                         # Proxmox Backup Server namespace

# Export PBS password from config
os.environ['PBS_PASSWORD'] = config['settings']['pbs_key']

def get_container_path(server_id):
    """
    Get the Docker volume path for a given server ID.
    Raises ValueError if no matching path or multiple paths found.
    """
    matches = glob.glob(f"{VOLUMES_PATH}/{server_id}*")
    if len(matches) > 1:
        raise ValueError(f"Multiple directories found for server ID {server_id}")
    elif len(matches) == 0:
        raise ValueError(f"No directory found for server ID {server_id}")
    return matches[0]

def run_command(cmd, cwd=None, timeout=14400):
    """
    Execute a shell command with logging and error handling.
    Returns True if successful, False otherwise.
    """
    logger.info(f"Executing command: {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True
        )
        if result.stdout:
            logger.debug(f"Command output: {result.stdout}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout} seconds: {cmd}")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}: {cmd}")
        if e.stdout:
            logger.error(f"stdout: {e.stdout}")
        if e.stderr:
            logger.error(f"stderr: {e.stderr}")
        return False

def manage_container(server_id, action):
    """
    Manage Docker container state (start/stop/kill).
    Returns True if successful, False otherwise.
    """
    # Get full container name
    cmd = f"docker ps -a --format '{{{{.Names}}}}' | grep '^{server_id}'"
    try:
        containers = subprocess.check_output(cmd, shell=True, text=True).strip().split('\n')
        if not containers or containers == ['']:
            logger.error(f"No container found for server ID {server_id}")
            return False
        if len(containers) > 1:
            logger.error(f"Multiple containers found for server ID {server_id}")
            return False
        container_name = containers[0]
        return run_command(f"docker {action} {container_name}")
    except subprocess.CalledProcessError:
        logger.error(f"Failed to get container name for server ID {server_id}")
        return False

def backup_server(server_id, config):
    """
    Perform backup of a server to Proxmox Backup Server.
    Handles container shutdown if configured and manages exclude paths.
    """
    logger.info(f"Starting backup for {server_id}")
    
    try:
        container_path = get_container_path(server_id)
    except ValueError as e:
        logger.error(str(e))
        return False

    # Check if container needs to be stopped
    container_was_running = False
    if config.get("shutdown", False):
        # Check if container is running using docker ps (no -a flag)
        cmd = f"docker ps --format '{{{{.Names}}}}' | grep '^{server_id}'"
        try:
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            container_was_running = bool(result)
            if container_was_running:
                if not manage_container(server_id, "stop"):
                    logger.error(f"Failed to stop container {server_id}")
                    return False
        except subprocess.CalledProcessError:
            # Grep returns non-zero if container not found (not running)
            container_was_running = False

    try:
        # Build exclude arguments for ignored paths
        exclude_args = []
        ignore_paths = config.get("ignore_paths", [])
        if ignore_paths:
            for rel_path in ignore_paths:
                abs_path = os.path.join(container_path, rel_path)
                exclude_args.extend(["--exclude", abs_path])

        # Construct backup command
        cmd = [
            "proxmox-backup-client", "backup",
            f"\"{server_id}.pxar:{container_path}\"",
            "--repository", f"'{PBS_REPOSITORY}'",
            "--ns", PBS_NAMESPACE,
            "--backup-type", "host",
            "--change-detection-mode", "metadata",
            "--backup-id", server_id
        ] + exclude_args

        # Execute command and capture output
        process = subprocess.Popen(" ".join(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        
        # Log the output
        if stdout:
            logger.info(f"Backup output for {server_id}:\n{stdout}")
        if stderr:
            # PBS outputs progress to stderr but these aren't actual errors
            logger.info(f"Backup progress for {server_id}:\n{stderr}")
            
        success = process.returncode == 0
        if success:
            logger.info(f"Backup completed successfully for {server_id}")
        else:
            logger.error(f"Backup failed for {server_id}")
        
        return success

    finally:
        # Restart container only if it was running before
        if config.get("shutdown", False) and container_was_running:
            if not manage_container(server_id, "start"):
                logger.error(f"Failed to start container {server_id}")

def restore_server(server_id, snapshot_name):
    """
    Restore a server from a Proxmox Backup Server snapshot.
    Creates a backup of current state before restoring.
    """
    logger.info(f"Starting restore for {server_id} using snapshot {snapshot_name}")
    
    try:
        container_path = get_container_path(server_id)
    except ValueError as e:
        logger.error(str(e))
        return False

    # Force stop the container for restore
    if not manage_container(server_id, "kill"):
        logger.error(f"Failed to kill container {server_id}")
        return False

    try:
        # Delete contents of container directory before restore
        for item in os.listdir(container_path):
            item_path = os.path.join(container_path, item)
            try:
                if os.path.isfile(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                logger.error(f"Failed to delete {item_path}: {e}")
                return False
        
        # Construct and execute restore command
        cmd = [
            "proxmox-backup-client", "restore", 
            f"{snapshot_name}",
            f"\"{server_id}.ppxar\"",
            f"\"{container_path}\"",
            "--repository", f"'{PBS_REPOSITORY}'",
            "--ns", PBS_NAMESPACE
        ]

        if run_command(" ".join(cmd)):
            logger.info(f"Restore completed successfully for {server_id}")
            return True
        else:
            logger.error(f"Restore failed for {server_id}")
            return False

    finally:
        pass

def schedule_jobs(scheduler, config):
    """
    Schedule backup jobs for all servers in config using cron expressions.
    """
    for server_id, settings in config["servers"].items():
        try:
            # Parse cron expression
            cron_expr = settings["schedule"].split()
            if len(cron_expr) != 5:
                logger.error(f"Invalid cron format for {server_id}, skipping.")
                continue
                
            minute, hour, dom, month, dow = cron_expr
            trigger = CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow)

            # Add job to scheduler
            scheduler.add_job(
                backup_server,
                trigger,
                args=[server_id, settings],
                id=server_id,
                name=f"Backup {server_id}",
                misfire_grace_time=3600
            )
            logger.info(f"Scheduled backup for {server_id} with schedule: {settings['schedule']}")
        except Exception as e:
            logger.error(f"Failed to schedule backup for {server_id}: {e}")

def list_snapshots(server_id):
    """
    List available snapshots for a server from Proxmox Backup Server.
    """
    logger.info(f"Listing snapshots for {server_id}")
    cmd = [
        "proxmox-backup-client", "snapshots",
        "--repository", f"'{PBS_REPOSITORY}'",
        "--ns", PBS_NAMESPACE
    ]
    
    process = subprocess.Popen(" ".join(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    if process.returncode != 0:
        logger.error(f"Failed to list snapshots: {stderr}")
        return []
    
    # Parse the output to find snapshots for the specific server
    snapshots = []
    for line in stdout.splitlines():
        if server_id in line:
            snapshots.append(line.strip())
    
    return snapshots

def main():
    """
    Main function: Parse command-line arguments and either start scheduler or perform restoration.
    """
    parser = argparse.ArgumentParser(description='Pterodactyl server backup and restore utility')
    parser.add_argument('--backup', action='store_true', help='Perform a manual backup')
    parser.add_argument('--restore', action='store_true', help='Restore mode')
    parser.add_argument('--server-id', help='Server ID for backup/restore operation')
    parser.add_argument('--snapshot', help='Snapshot name for restore operation')
    parser.add_argument('--list-snapshots', action='store_true', help='List available snapshots for a server')
    parser.add_argument('--shutdown', action='store_true', help='Force shutdown during backup (overrides config)')
    
    args = parser.parse_args()
    
    if args.list_snapshots:
        if not args.server_id:
            logger.error("Server ID is required for listing snapshots")
            sys.exit(1)
        snapshots = list_snapshots(args.server_id)
        if snapshots:
            print("\nAvailable snapshots:")
            for snapshot in snapshots:
                print(snapshot)
        else:
            print("No snapshots found")
        sys.exit(0)
    
    if args.backup:
        if not args.server_id:
            logger.error("Server ID is required for backup")
            sys.exit(1)
            
        # Get server config if it exists, or create minimal config
        server_config = config['servers'].get(args.server_id, {})
        if args.shutdown:
            server_config['shutdown'] = True
            
        if backup_server(args.server_id, server_config):
            logger.info("Backup completed successfully")
            sys.exit(0)
        else:
            logger.error("Backup failed")
            sys.exit(1)
    
    if args.restore:
        if not args.server_id or not args.snapshot:
            logger.error("Both server ID and snapshot name are required for restore")
            sys.exit(1)
        if restore_server(args.server_id, args.snapshot):
            logger.info("Restore completed successfully")
            sys.exit(0)
        else:
            logger.error("Restore failed")
            sys.exit(1)
    
    # Regular scheduler mode
    scheduler = BlockingScheduler()
    shutdown_flag = False
    
    def shutdown(signum, frame):
        """Signal handler for graceful shutdown"""
        nonlocal shutdown_flag
        if shutdown_flag:
            return
        shutdown_flag = True
        logger.info("Shutdown signal received, stopping scheduler...")
        try:
            scheduler.shutdown()
        except:
            pass
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    import signal
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    # Start the scheduler
    schedule_jobs(scheduler, config)
    logger.info("Starting backup scheduler")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        if not shutdown_flag:  # Only call shutdown if not already shutting down
            shutdown(None, None)

if __name__ == "__main__":
    main()
