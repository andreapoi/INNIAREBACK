from pathlib import Path
import shutil

BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")

DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"


def get_latest_backup():

    backups = sorted(
        [
            p
            for p in BACKUP_DIR.iterdir()
            if p.is_dir() and p.name.startswith("backup_")
        ]
    )

    if not backups:
        raise FileNotFoundError(
            "Nessun backup trovato."
        )

    return backups[-1]


def restore_tournament():

    backup_path = get_latest_backup()

    restored = 0

    for file_path in backup_path.glob("*"):

        shutil.copy2(
            file_path,
            DATA_DIR / file_path.name
        )

        restored += 1

    print(f"Backup ripristinato: {backup_path}")
    print(f"File ripristinati: {restored}")


if __name__ == "__main__":
    restore_tournament()