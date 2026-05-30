# utils/fifa_parser.py

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import pandas as pd


MATCH_COLUMNS = [
    "match_id",
    "stage",
    "group",
    "matchday",
    "datetime",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "real_scorers",
]


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def load_team_mapping(mapping_path: str | Path) -> dict[str, str]:
    mapping_path = Path(mapping_path)

    if not mapping_path.exists():
        raise FileNotFoundError(f"File mapping non trovato: {mapping_path}")

    df = pd.read_csv(mapping_path, sep=None, engine="python", encoding="utf-8-sig")

    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.lower()
    )

    print(f"Colonne lette da team_mapping.csv: {list(df.columns)}")

    required_cols = {"raw_name", "team_name"}

    if not required_cols.issubset(df.columns):
        raise ValueError(
            f"{mapping_path} deve contenere almeno le colonne: "
            f"{', '.join(sorted(required_cols))}. "
            f"Colonne trovate: {list(df.columns)}"
        )

    df["raw_name"] = df["raw_name"].astype(str).str.strip()
    df["team_name"] = df["team_name"].astype(str).str.strip()

    df = df[df["raw_name"] != ""]
    df = df[df["team_name"] != ""]

    return dict(zip(df["raw_name"], df["team_name"]))


def normalize_team_name(team_name: str, mapping: dict[str, str]) -> str:
    team_name = clean_text(team_name)

    if team_name in mapping:
        return mapping[team_name]

    print(f"[WARNING] Team non mappato in team_mapping.csv: {team_name}")

    return team_name


def extract_calendar_text_from_html(html: str) -> str:
    """
    Estrae dall'HTML FIFA il blocco testuale più lungo
    che contiene il calendario.
    """

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    candidate_blocks = []

    for tag in soup.find_all(["main", "article", "section", "div", "li"]):
        text = clean_text(tag.get_text(" "))

        if not text:
            continue

        if "First Stage" in text and "Group" in text and "June 2026" in text:
            candidate_blocks.append(text)

    if not candidate_blocks:
        raise RuntimeError(
            "Nessun blocco calendario trovato nell'HTML FIFA."
        )

    return max(candidate_blocks, key=len)


def parse_group_stage_matches(
    calendar_text: str,
    mapping_path: str | Path,
) -> pd.DataFrame:
    """
    Converte il calendario testuale FIFA in matches.csv.

    Output:
    match_id,stage,group,matchday,datetime,home_team,away_team,home_score,away_score
    """

    team_mapping = load_team_mapping(mapping_path)

    date_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) "
        r"\d{1,2} [A-Za-z]+ 2026"
    )

    match_pattern = re.compile(
        r"\b([A-Z]{3})\s+(.+?)\s+"
        r"(\d{2}:\d{2})\s+"
        r"([A-Z]{3})\s+(.+?)\s+"
        r"First Stage\s+·\s+Group\s+([A-L])\s+·"
    )

    date_matches = list(date_pattern.finditer(calendar_text))

    if not date_matches:
        raise RuntimeError("Nessuna data trovata nel calendario FIFA.")

    rows = []

    for i, date_match in enumerate(date_matches):
        full_date = date_match.group(0)

        start = date_match.end()
        end = (
            date_matches[i + 1].start()
            if i + 1 < len(date_matches)
            else len(calendar_text)
        )

        day_chunk = calendar_text[start:end]

        for match in match_pattern.finditer(day_chunk):
            (
                home_code,
                raw_home_team,
                time_str,
                away_code,
                raw_away_team,
                group,
            ) = match.groups()

            date_clean = re.sub(
                r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) ",
                "",
                full_date,
            )

            dt = datetime.strptime(
                f"{date_clean} {time_str}",
                "%d %B %Y %H:%M",
            )

            home_team = normalize_team_name(raw_home_team, team_mapping)
            away_team = normalize_team_name(raw_away_team, team_mapping)

            rows.append(
                {
                    "stage": "Group Stage",
                    "group": group,
                    "datetime": dt,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": pd.NA,
                    "away_score": pd.NA,
                    "real_scorers": ""
                }
            )

    df = pd.DataFrame(rows)

    if df.empty:
        raise RuntimeError("Parsing fallito: nessuna partita trovata.")

    df = df.drop_duplicates(
        subset=["datetime", "home_team", "away_team", "group"]
    )

    df = df.sort_values(
        by=["datetime", "home_team", "away_team"],
        ascending=True,
    ).reset_index(drop=True)

    df.insert(0, "match_id", range(1, len(df) + 1))

    df["matchday"] = df.groupby("group").cumcount() // 2 + 1

    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d %H:%M")

    return df[MATCH_COLUMNS]


def preserve_existing_scores(
    new_df: pd.DataFrame,
    existing_matches_path: str | Path,
) -> pd.DataFrame:
    """
    Mantiene home_score, away_score e real_scorers già presenti in matches.csv.
    Usa match_id come chiave primaria.
    """

    existing_matches_path = Path(existing_matches_path)

    if not existing_matches_path.exists():
        return new_df[MATCH_COLUMNS]

    old_df = pd.read_csv(
        existing_matches_path,
        sep=None,
        engine="python",
        encoding="utf-8-sig",
    )

    old_df.columns = (
        old_df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    key_cols = ["match_id"]
    preserve_cols = ["home_score", "away_score", "real_scorers"]

    required_cols = set(key_cols + preserve_cols)

    if not required_cols.issubset(old_df.columns):
        print(
            "[WARNING] matches.csv esistente non compatibile. "
            "Non preservo risultati/marcatori."
        )
        return new_df[MATCH_COLUMNS]

    old_df["match_id"] = old_df["match_id"].astype(int)
    new_df["match_id"] = new_df["match_id"].astype(int)

    old_data = old_df[key_cols + preserve_cols].copy()

    merged = new_df.merge(
        old_data,
        on=key_cols,
        how="left",
        suffixes=("", "_old"),
    )

    for col in preserve_cols:
        old_col = f"{col}_old"

        if old_col in merged.columns:
            merged[col] = merged[old_col].combine_first(merged[col])
            merged = merged.drop(columns=[old_col])

    return merged[MATCH_COLUMNS]