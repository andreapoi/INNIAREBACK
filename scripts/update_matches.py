# scripts/update_matches.py

from pathlib import Path
import sys
import pandas as pd


BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = BASE_DIR / "scripts"

MATCHES_PATH = DATA_DIR / "matches.csv"
BACKUP_DIR = DATA_DIR / "backups"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.scrape_matches import scrape_html
from utils.fifa_parser import (
    extract_calendar_text_from_html,
    parse_group_stage_matches,
    preserve_existing_scores,
)


TEAM_MAPPING_PATH = DATA_DIR / "team_mapping.csv"


def backup_existing_matches() -> Path | None:
    if not MATCHES_PATH.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"matches_backup_{timestamp}.csv"

    old_df = pd.read_csv(MATCHES_PATH)
    old_df.to_csv(backup_path, index=False, encoding="utf-8")

    return backup_path


def update_matches() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Avvio aggiornamento matches.csv...")

    backup_path = backup_existing_matches()

    if backup_path:
        print(f"Backup creato: {backup_path}")
    else:
        print("Nessun matches.csv esistente: backup non necessario.")

    print("Scarico calendario FIFA...")
    html = scrape_html()

    print("Estraggo testo calendario...")
    calendar_text = extract_calendar_text_from_html(html)

    print("Parsing partite fase a gironi...")
    new_df = parse_group_stage_matches(
        calendar_text=calendar_text,
        mapping_path=TEAM_MAPPING_PATH,
    )

    print("Preservo risultati già inseriti...")
    final_df = preserve_existing_scores(
        new_df=new_df,
        existing_matches_path=MATCHES_PATH,
    )

    final_df.to_csv(MATCHES_PATH, index=False, encoding="utf-8")

    print(f"matches.csv aggiornato: {MATCHES_PATH}")
    print(f"Partite totali: {len(final_df)}")
    print(final_df.head(10).to_string(index=False))

    return final_df


def main() -> None:
    update_matches()


if __name__ == "__main__":
    main()
