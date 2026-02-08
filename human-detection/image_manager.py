"""
Image Management Module
Handles purging of old image folders based on retention policy.
"""

import os
import shutil
from datetime import datetime, timedelta
import threading
import time
import schedule


def purge_old_folders(config: dict):
    """
    Delete image folders older than the retention period defined in config.
    
    Args:
        config: Configuration dictionary containing image_storage settings
    """
    base_folder = config.get("image_storage", {}).get("base_folder", "captured_images")
    purge_after_days = config.get("image_storage", {}).get("purge_after_days", 2)
    
    if not os.path.exists(base_folder):
        print(f"Base folder '{base_folder}' does not exist. Nothing to purge.")
        return
    
    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=purge_after_days)
    cutoff_date_str = cutoff_date.strftime("%Y%m%d")
    
    print(f"[PURGE] Scanning for folders older than {purge_after_days} days (before {cutoff_date_str})...")
    
    deleted_count = 0
    
    # Iterate through subdirectories
    for folder_name in os.listdir(base_folder):
        folder_path = os.path.join(base_folder, folder_name)
        
        # Skip if not a directory
        if not os.path.isdir(folder_path):
            continue
        
        # Check if folder name is a valid date (YYYYMMDD format)
        if len(folder_name) == 8 and folder_name.isdigit():
            try:
                folder_date = datetime.strptime(folder_name, "%Y%m%d")
                
                # Delete if older than cutoff date
                if folder_date < cutoff_date:
                    shutil.rmtree(folder_path)
                    deleted_count += 1
                    print(f"  [PURGE] Deleted: {folder_path}")
                    
            except ValueError:
                # Invalid date format, skip
                print(f"  [PURGE] Skipped (invalid date format): {folder_name}")
                continue
    
    if deleted_count > 0:
        print(f"✓ [PURGE] Removed {deleted_count} old folder(s)")
    else:
        print("✓ [PURGE] No old folders to purge")


def get_folder_size_mb(folder_path: str) -> float:
    """
    Calculate total size of a folder in MB.
    
    Args:
        folder_path: Path to the folder
        
    Returns:
        Size in megabytes
    """
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
    
    return total_size / (1024 * 1024)  # Convert to MB


def _run_scheduler(config: dict):
    """
    Background thread that runs the schedule checker.
    
    Args:
        config: Configuration dictionary
    """
    print("[SCHEDULER] Image purge scheduler started")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def start_purge_scheduler(config: dict):
    """
    Start a background cron job to purge old image folders.
    
    Uses the cron_job settings from config:
    - cron_job.enabled: Whether to start the scheduler
    - cron_job.schedule: Cron expression (e.g., "0 0 * * *" for daily at midnight)
    
    Args:
        config: Configuration dictionary containing cron_job settings
    """
    cron_config = config.get("cron_job", {})
    
    if not cron_config.get("enabled", False):
        print("[SCHEDULER] Purge scheduler disabled in config")
        return
    
    cron_schedule = cron_config.get("schedule", "0 0 * * *")
    
    # Parse cron expression (format: "minute hour day month weekday")
    # For simplicity, we'll support common patterns:
    # "0 0 * * *" = daily at midnight
    # "0 */6 * * *" = every 6 hours
    # "*/30 * * * *" = every 30 minutes
    
    parts = cron_schedule.split()
    
    if len(parts) >= 2:
        minute = parts[0]
        hour = parts[1]
        
        # Daily at specific time
        if minute.isdigit() and hour.isdigit():
            schedule_time = f"{hour.zfill(2)}:{minute.zfill(2)}"
            schedule.every().day.at(schedule_time).do(purge_old_folders, config)
            print(f"[SCHEDULER] Scheduled daily purge at {schedule_time}")
        
        # Every N hours
        elif hour.startswith("*/"):
            interval = int(hour.replace("*/", ""))
            schedule.every(interval).hours.do(purge_old_folders, config)
            print(f"[SCHEDULER] Scheduled purge every {interval} hours")
        
        # Every N minutes
        elif minute.startswith("*/"):
            interval = int(minute.replace("*/", ""))
            schedule.every(interval).minutes.do(purge_old_folders, config)
            print(f"[SCHEDULER] Scheduled purge every {interval} minutes")
        
        else:
            # Default to daily at midnight
            schedule.every().day.at("00:00").do(purge_old_folders, config)
            print(f"[SCHEDULER] Using default schedule: daily at midnight")
    else:
        # Default to daily at midnight
        schedule.every().day.at("00:00").do(purge_old_folders, config)
        print(f"[SCHEDULER] Using default schedule: daily at midnight")
    
    # Run purge once immediately on startup
    print("[SCHEDULER] Running initial purge...")
    purge_old_folders(config)
    
    # Start background thread
    scheduler_thread = threading.Thread(target=_run_scheduler, args=(config,), daemon=True)
    scheduler_thread.start()
    print("[SCHEDULER] Background scheduler thread started")


if __name__ == "__main__":
    # Can be run standalone for testing or via cron
    import yaml
    
    with open("configs/env_var.yaml", "r") as f:
        config = yaml.safe_load(f)
    
    start_purge_scheduler(config)
