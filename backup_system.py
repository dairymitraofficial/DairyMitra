import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("MYSQL_HOST")
DB_PORT = int(os.getenv("MYSQL_PORT", 3306))
DB_USER = os.getenv("MYSQL_USER")
DB_PASS = os.getenv("MYSQL_PASSWORD")
DB_NAME = os.getenv("MYSQL_DB")


# ----------------------------
# CREATE USER BACKUP
# ----------------------------
def create_user_backup(user_id):

    os.makedirs("backups", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"user_{user_id}_backup_{timestamp}.sql"
    filepath = os.path.join("backups", filename)

    command = [
        "mysqldump",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME,
        "--no-create-info",
        "--skip-triggers"
    ]

    with open(filepath, "w") as f:
        subprocess.run(command, stdout=f, check=True)

    return filename


# ----------------------------
# FULL DATABASE BACKUP
# ----------------------------
def create_full_backup():

    os.makedirs("backups", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"full_backup_{timestamp}.sql"
    filepath = os.path.join("backups", filename)

    command = [
        "mysqldump",
        "--single-transaction",
        "--quick",
        "--lock-tables=false",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME
    ]

    with open(filepath, "w") as f:
        subprocess.run(command, stdout=f, check=True)

    return filename


# ----------------------------
# SIMPLE BACKUP
# ----------------------------
def create_backup():

    os.makedirs("backups", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql"
    filepath = os.path.join("backups", filename)

    command = [
        "mysqldump",
        "--single-transaction",
        "--quick",
        "--lock-tables=false",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME
    ]

    with open(filepath, "w") as f:
        subprocess.run(command, stdout=f, check=True)

    return filename


# ----------------------------
# GOOGLE DRIVE UPLOAD (dummy)
# ----------------------------
def upload_to_drive(file):
    print("Uploading to drive:", file)


# ----------------------------
# AUTOMATIC BACKUP
# ----------------------------
def automatic_backup():

    print("Running automatic backup...")

    filename = create_backup()

    upload_to_drive(filename)

    print("Automatic backup completed")


# ----------------------------
# RESTORE USER BACKUP
# ----------------------------
def restore_user_backup(filepath, user_id):

    os.makedirs("backups", exist_ok=True)

    # safety backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_file = f"backups/safety_backup_user_{user_id}_{timestamp}.sql"

    dump_command = [
        "mysqldump",
        "--single-transaction",
        "--quick",
        "--lock-tables=false",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME
    ]

    with open(safety_file, "w") as f:
        subprocess.run(dump_command, stdout=f, check=True)

    print("Safety backup created:", safety_file)

    # restore
    restore_command = [
        "mysql",
        "-h", DB_HOST,
        "-P", str(DB_PORT),
        "-u", DB_USER,
        f"-p{DB_PASS}",
        DB_NAME
    ]

    with open(filepath, "rb") as sql_file:
        subprocess.run(restore_command, stdin=sql_file, check=True)

    print("Restore completed")

    return True