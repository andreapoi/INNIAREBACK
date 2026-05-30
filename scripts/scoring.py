# scripts/scoring.py

from pathlib import Path
import pandas as pd


BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")
DATA_DIR = BASE_DIR / "data"

MATCHES_PATH = DATA_DIR / "matches.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
STANDINGS_PATH = DATA_DIR / "standings.csv"
PLAYER_POINTS_PATH = DATA_DIR / "player_points.csv"


POINTS_EXACT_SCORE = 5
POINTS_1X2 = 2
POINTS_SCORER = 3.5

def clean_value(value) -> str:
    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    return value.upper()


def calc_result(home_score, away_score) -> str:
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


def exact_score_correct(row) -> bool:
    return (
        not pd.isna(row["pred_home_score"])
        and not pd.isna(row["pred_away_score"])
        and not pd.isna(row["home_score"])
        and not pd.isna(row["away_score"])
        and int(row["pred_home_score"]) == int(row["home_score"])
        and int(row["pred_away_score"]) == int(row["away_score"])
    )


def result_1x2_correct(row) -> bool:
    pred_result = clean_value(row["pred_result"])

    if pred_result == "":
        pred_result = calc_result(
            row["pred_home_score"],
            row["pred_away_score"],
        )

    real_result = calc_result(
        row["home_score"],
        row["away_score"],
    )

    return pred_result != "" and pred_result == real_result


def scorer_correct(row) -> bool:
    pred_scorer = clean_value(row["pred_scorer"])
    real_scorers = clean_value(row["real_scorers"])

    # Caso nessun marcatore previsto e nessun marcatore reale
    if pred_scorer == "" and real_scorers == "":
        return True

    # Caso marcatore previsto ma nessun marcatore reale
    if pred_scorer != "" and real_scorers == "":
        return False

    # Caso nessun marcatore previsto ma almeno un marcatore reale
    if pred_scorer == "" and real_scorers != "":
        return False

    real_scorers_list = [
        scorer.strip().lower()
        for scorer in real_scorers.split(";")
        if scorer.strip()
    ]

    return pred_scorer.lower() in real_scorers_list


def score_row(row) -> pd.Series:
    exact = exact_score_correct(row)
    result = result_1x2_correct(row)
    scorer = scorer_correct(row)

    exact_points = POINTS_EXACT_SCORE if exact else 0
    result_points = POINTS_1X2 if result else 0
    scorer_points = POINTS_SCORER if scorer else 0

    total_points = exact_points + result_points + scorer_points

    return pd.Series(
        {
            "exact_score_points": exact_points,
            "result_1x2_points": result_points,
            "scorer_points": scorer_points,
            "total_points": total_points,
        }
    )


def load_data() -> pd.DataFrame:
    matches = pd.read_csv(
    MATCHES_PATH,
    sep=None,
    engine="python",
    encoding="utf-8-sig"
    )
    predictions = pd.read_csv(
    PREDICTIONS_PATH,
    sep=None,
    engine="python",
    encoding="utf-8-sig"
    )
    
    matches.columns = matches.columns.astype(str).str.strip()
    predictions.columns = predictions.columns.astype(str).str.strip()

    required_matches = {
        "match_id",
        "home_score",
        "away_score",
        "real_scorers",
    }

    required_predictions = {
        "partecipant",
        "match_id",
        "pred_home_score",
        "pred_away_score",
        "pred_result",
        "pred_scorer",
    }

    if not required_matches.issubset(matches.columns):
        raise ValueError(
            f"matches.csv manca colonne: {required_matches - set(matches.columns)}"
        )

    if not required_predictions.issubset(predictions.columns):
        raise ValueError(
            f"predictions.csv manca colonne: {required_predictions - set(predictions.columns)}"
        )

    df = predictions.merge(
        matches,
        on="match_id",
        how="left",
        suffixes=("_pred", "_real"),
    )

    # Calcolo solo partite concluse
    df = df[
        df["home_score"].notna()
        & df["away_score"].notna()
    ].copy()

    return df


def calculate_player_points() -> pd.DataFrame:
    df = load_data()

    if df.empty:
        print("Nessuna partita con risultato reale inserito.")
        return pd.DataFrame()

    points = df.apply(score_row, axis=1)
    df = pd.concat([df, points], axis=1)

    keep_cols = [
        "partecipant",
        "match_id",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "real_scorers",
        "pred_home_score",
        "pred_away_score",
        "pred_result",
        "pred_scorer",
        "exact_score_points",
        "result_1x2_points",
        "scorer_points",
        "total_points",
    ]

    return df[keep_cols]


def calculate_standings(player_points: pd.DataFrame) -> pd.DataFrame:
    standings = (
        player_points
        .groupby("partecipant", as_index=False)
        .agg(
            total_points=("total_points", "sum"),
            exact_scores=("exact_score_points", lambda x: (x > 0).sum()),
            correct_1x2=("result_1x2_points", lambda x: (x > 0).sum()),
            correct_scorers=("scorer_points", lambda x: (x > 0).sum()),
            matches_scored=("match_id", "count"),
        )
    )

    standings = standings.sort_values(
        by=["total_points", "exact_scores", "correct_scorers", "correct_1x2"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    standings.insert(0, "rank", range(1, len(standings) + 1))

    return standings


def run_scoring() -> tuple[pd.DataFrame, pd.DataFrame]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    player_points = calculate_player_points()

    if player_points.empty:
        return player_points, pd.DataFrame()

    standings = calculate_standings(player_points)

    player_points.to_csv(PLAYER_POINTS_PATH, index=False, encoding="utf-8")
    standings.to_csv(STANDINGS_PATH, index=False, encoding="utf-8")

    print(f"Creato/aggiornato: {PLAYER_POINTS_PATH}")
    print(f"Creato/aggiornato: {STANDINGS_PATH}")
    print(standings.to_string(index=False))

    return player_points, standings


def main() -> None:
    run_scoring()


if __name__ == "__main__":
    main()