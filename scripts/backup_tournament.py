from pathlib import Path
import shutil
import pandas as pd

BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")

DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"

FILES_TO_BACKUP = [
    "matches.csv",
    "predictions.csv",
    "partecipants.csv",
    "team_mapping.csv",
    "standings.csv",
    "player_points.csv",
]


def backup_tournament():

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    backup_path = BACKUP_DIR / f"backup_{timestamp}"

    backup_path.mkdir(parents=True, exist_ok=True)

    copied = 0

    for filename in FILES_TO_BACKUP:

        source = DATA_DIR / filename

        if source.exists():

            shutil.copy2(
                source,
                backup_path / filename
            )

            copied += 1

    print(f"Backup creato: {backup_path}")
    print(f"File copiati: {copied}")

    return backup_path


if __name__ == "__main__":
    backup_tournament()