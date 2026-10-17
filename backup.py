"""Make a timestamped copy of the database and keep only the newest ones.

Usage:  python backup.py [backup_folder] [number_to_keep]
Run it on a schedule (cron, Task Scheduler) wherever the database lives permanently.
Staff can also download a snapshot from the System page in the app.
"""

import os
import sqlite3
import sys
from datetime import datetime

from db import DATABASE


def backup(folder="backups", keep=14):
    os.makedirs(folder, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    target_path = os.path.join(folder, f"asclepio-backup-{stamp}.sqlite")
    counter = 1
    while os.path.exists(target_path):
        counter += 1
        target_path = os.path.join(folder, f"asclepio-backup-{stamp}-{counter}.sqlite")
    source = sqlite3.connect(DATABASE)
    target = sqlite3.connect(target_path)
    with target:
        source.backup(target)
    source.close()
    target.close()

    backups = sorted(f for f in os.listdir(folder) if f.startswith("asclepio-backup-") and f.endswith(".sqlite"))
    for old in backups[:-keep]:
        os.remove(os.path.join(folder, old))
    return target_path


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "backups"
    keep = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    print(f"Backup written to {backup(folder, keep)}")
