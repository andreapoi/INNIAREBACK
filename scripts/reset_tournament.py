from pathlib import Path
import pandas as pd

BASE_DIR = Path("/Users/user/Desktop/INNIAREBACK")

DATA_DIR = BASE_DIR / "data"

MATCHES_PATH = DATA_DIR / "matches.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"

STANDINGS_PATH = DATA_DIR / "standings.csv"
PLAYER_POINTS_PATH = DATA_DIR / "player_points.csv"


def reset_matches():

    if not MATCHES_PATH.exists():
        return

    df = pd.read_csv(MATCHES_PATH)

    if "home_score" in df.columns:
        df["home_score"] = pd.NA

    if "away_score" in df.columns:
        df["away_score"] = pd.NA

    if "real_scorers" in df.columns:
        df["real_scorers"] = ""

    df.to_csv(
        MATCHES_PATH,
        index=False,
        encoding="utf-8"
    )

    print("matches.csv resettato")


def reset_predictions():

    print(f"PREDICTIONS_PATH = {PREDICTIONS_PATH}")
    print(f"EXISTS = {PREDICTIONS_PATH.exists()}")

    if not PREDICTIONS_PATH.exists():
        print("predictions.csv non trovato")
        return

    df = pd.read_csv(
        PREDICTIONS_PATH,
        sep=None,
        engine="python",
        encoding="utf-8-sig",
    )

    df.columns = df.columns.astype(str).str.strip()

    cols_to_reset = [
        "pred_home_score",
        "pred_away_score",
        "pred_result",
        "pred_scorer",
        "last_update",
    ]

    for col in cols_to_reset:
        if col in df.columns:
            df[col] = ""
        else:
            print(f"[WARNING] Colonna non trovata in predictions.csv: {col}")

    df.to_csv(
        PREDICTIONS_PATH,
        index=False,
        encoding="utf-8",
    )

    print("predictions.csv resettato")


def remove_outputs():

    for path in [
        STANDINGS_PATH,
        PLAYER_POINTS_PATH,
    ]:

        if path.exists():
            path.unlink()
            print(f"Eliminato {path.name}")


def reset_tournament():

    reset_matches()
    reset_predictions()
    remove_outputs()

    print()
    print("Torneo resettato.")


if __name__ == "__main__":
    reset_tournament()