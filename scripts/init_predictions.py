# scripts/init_predictions.py

from pathlib import Path
import sys
import pandas as pd


BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")
DATA_DIR = BASE_DIR / "data"

MATCHES_PATH = DATA_DIR / "matches.csv"
PARTICIPANTS_PATH = DATA_DIR / "partecipants.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"

PREDICTION_COLUMNS = [
    "partecipant",
    "match_id",
    "pred_home_score",
    "pred_away_score",
    "pred_result",
    "pred_scorer",
    "last_update",
]


def calculate_result(home_score, away_score):
    if pd.isna(home_score) or pd.isna(away_score):
        return ""

    home_score = int(home_score)
    away_score = int(away_score)

    if home_score > away_score:
        return "1"
    elif home_score < away_score:
        return "2"
    else:
        return "X"


def load_participants() -> pd.DataFrame:
    if not PARTICIPANTS_PATH.exists():
        raise FileNotFoundError(
            f"File partecipanti non trovato: {PARTICIPANTS_PATH}"
        )

    df = pd.read_csv(PARTICIPANTS_PATH)

    if "partecipant" not in df.columns:
        raise ValueError(
            "participants.csv deve contenere la colonna: participant"
        )

    df["partecipant"] = df["partecipant"].astype(str).str.strip()
    df = df[df["partecipant"] != ""]
    df = df.drop_duplicates(subset=["partecipant"])

    return df


def load_matches() -> pd.DataFrame:
    if not MATCHES_PATH.exists():
        raise FileNotFoundError(
            f"File partite non trovato: {MATCHES_PATH}"
        )

    df = pd.read_csv(MATCHES_PATH)

    if "match_id" not in df.columns:
        raise ValueError(
            "matches.csv deve contenere la colonna: match_id"
        )

    return df


def build_empty_predictions(
    partecipants_df: pd.DataFrame,
    matches_df: pd.DataFrame,
) -> pd.DataFrame:

    partecipants = partecipants_df["partecipant"].tolist()
    match_ids = matches_df["match_id"].tolist()

    rows = []

    for partecipant in partecipants:
        for match_id in match_ids:
            rows.append(
                {
                    "partecipant": partecipant,
                    "match_id": match_id,
                    "pred_home_score": pd.NA,
                    "pred_away_score": pd.NA,
                    "pred_result": "",
                    "pred_scorer": "",
                    "last_update": "",
                }
            )

    return pd.DataFrame(rows, columns=PREDICTION_COLUMNS)


def preserve_existing_predictions(new_df: pd.DataFrame) -> pd.DataFrame:
    if not PREDICTIONS_PATH.exists():
        return new_df

    old_df = pd.read_csv(PREDICTIONS_PATH)

    required_cols = set(PREDICTION_COLUMNS)

    if not required_cols.issubset(old_df.columns):
        print("[WARNING] predictions.csv esistente non compatibile. Lo rigenero.")
        return new_df

    old_df = old_df[PREDICTION_COLUMNS].copy()

    merged = new_df.merge(
        old_df,
        on=["partecipant", "match_id"],
        how="left",
        suffixes=("", "_old"),
    )

    for col in [
        "pred_home_score",
        "pred_away_score",
        "pred_result",
        "last_update",
    ]:
        merged[col] = merged[f"{col}_old"].combine_first(merged[col])
        merged = merged.drop(columns=[f"{col}_old"])

    return merged[PREDICTION_COLUMNS]


def refresh_pred_result(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["pred_result"] = df.apply(
        lambda row: calculate_result(
            row["pred_home_score"],
            row["pred_away_score"],
        ),
        axis=1,
    )

    return df


def init_predictions() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    partecipants_df = load_participants()
    matches_df = load_matches()

    new_df = build_empty_predictions(
        partecipants_df=partecipants_df,
        matches_df=matches_df,
    )

    final_df = preserve_existing_predictions(new_df)
    final_df = refresh_pred_result(final_df)

    final_df.to_csv(PREDICTIONS_PATH, index=False, encoding="utf-8")

    print(f"Creato/aggiornato: {PREDICTIONS_PATH}")
    print(f"Partecipanti: {partecipants_df['partecipant'].nunique()}")
    print(f"Partite: {matches_df['match_id'].nunique()}")
    print(f"Righe predictions: {len(final_df)}")
    print(final_df.head(10).to_string(index=False))

    return final_df


def main() -> None:
    init_predictions()


if __name__ == "__main__":
    main()