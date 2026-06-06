from pathlib import Path
from datetime import datetime
import base64
import shutil

import pandas as pd
import requests
import streamlit as st

from auth import login_box, logout_button, user_is_admin

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"

MATCHES_PATH = DATA_DIR / "matches.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
PARTECIPANTS_PATH = DATA_DIR / "partecipants.csv"
TEAM_MAPPING_PATH = DATA_DIR / "team_mapping.csv"
MD_PLAYERS_PATH = DATA_DIR / "md_players.csv"
STANDINGS_PATH = DATA_DIR / "standings.csv"
PLAYER_POINTS_PATH = DATA_DIR / "player_points.csv"
USERS_PATH = DATA_DIR / "users.csv"

POINTS_EXACT_SCORE = 5
POINTS_1X2 = 2
POINTS_SCORER = 3.5
POINTS_OWN_GOAL = 2

STAGE_COL = "stato_avanzamento_torneo"
MATCH_DAY_COL = "match_day"
LOCK_TIMESTAMP_COL = "lock_timestamp"
PRED_OG_1 = "pred_autogol_squadra_1"
PRED_OG_2 = "pred_autogol_squadra_2"
REAL_OG_1 = "real_autogol_squadra_1"
REAL_OG_2 = "real_autogol_squadra_2"

CSV_FILES = [MATCHES_PATH, PREDICTIONS_PATH, PARTECIPANTS_PATH, TEAM_MAPPING_PATH, MD_PLAYERS_PATH, STANDINGS_PATH, PLAYER_POINTS_PATH, USERS_PATH]

st.set_page_config(page_title="INNIAREBACK Backend", page_icon="⚽", layout="wide")


def github_enabled() -> bool:
    return all(k in st.secrets for k in ["GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH"])


def get_github_config():
    return st.secrets["GITHUB_TOKEN"], st.secrets["GITHUB_REPO"], st.secrets.get("GITHUB_BRANCH", "main")


def github_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def github_get_file(path_in_repo: str):
    token, repo, branch = get_github_config()
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    r = requests.get(url, headers=github_headers(token), params={"ref": branch}, timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    payload = r.json()
    return base64.b64decode(payload["content"]).decode("utf-8"), payload["sha"]


def github_put_file(path_in_repo: str, content: str, message: str) -> None:
    token, repo, branch = get_github_config()
    _, sha = github_get_file(path_in_repo)
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    payload = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"), "branch": branch}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=github_headers(token), json=payload, timeout=30)
    r.raise_for_status()


def github_list_directory(path_in_repo: str) -> list[dict]:
    token, repo, branch = get_github_config()
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    r = requests.get(url, headers=github_headers(token), params={"ref": branch}, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    payload = r.json()
    return [payload] if isinstance(payload, dict) else payload


def repo_path(local_path: Path) -> str:
    return local_path.relative_to(BASE_DIR).as_posix()


def sync_file_from_github(local_path: Path) -> bool:
    if not github_enabled():
        return False
    content, _ = github_get_file(repo_path(local_path))
    if content is None:
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")
    return True


def sync_core_files_from_github() -> None:
    for path in CSV_FILES:
        try:
            sync_file_from_github(path)
        except Exception:
            pass


def save_text_and_push(local_path: Path, content: str, commit_message: str) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")
    if github_enabled():
        github_put_file(repo_path(local_path), content, commit_message)
    else:
        st.warning("GitHub non configurato nei Secrets: salvataggio solo locale.")


def save_csv_and_push(df: pd.DataFrame, path: Path, commit_message: str) -> None:
    save_text_and_push(path, df.to_csv(index=False), commit_message)


def save_empty_csv_and_push(path: Path, columns: list[str], commit_message: str) -> None:
    save_csv_and_push(pd.DataFrame(columns=columns), path, commit_message)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path, sync: bool = True) -> pd.DataFrame:
    if sync and github_enabled():
        try:
            sync_file_from_github(path)
        except Exception:
            pass
    if not path.exists():
        return pd.DataFrame()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if text.strip() == "":
        return pd.DataFrame()
    try:
        if ";" in text.splitlines()[0] and "," not in text.splitlines()[0]:
            df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
        else:
            df = pd.read_csv(path, sep=",", encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except Exception:
        try:
            df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        except Exception:
            return pd.DataFrame()
    df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
    if "participant" in df.columns and "partecipant" not in df.columns:
        df = df.rename(columns={"participant": "partecipant"})
    return df


def clean_value(value) -> str:
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    if value.lower() in ["nan", "none"]:
        return ""
    return value


def bool_value(value) -> bool:
    return clean_value(value).lower() in ["true", "1", "yes", "y", "si", "sì", "x"]


def clean_bool_series(series: pd.Series) -> pd.Series:
    return series.apply(bool_value).astype(bool)


def parse_datetime_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.fillna("").astype(str).str.strip(), errors="coerce", dayfirst=False)


def format_datetime_value(value) -> str:
    if pd.isna(value):
        return ""
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def now_dt() -> pd.Timestamp:
    return pd.Timestamp(datetime.now())


def is_locked_value(value) -> bool:
    parsed = pd.to_datetime(clean_value(value), errors="coerce")
    if pd.isna(parsed):
        return False
    return parsed <= now_dt()


def add_lock_timestamps(matches: pd.DataFrame) -> pd.DataFrame:
    """Set lock_timestamp by match_day: same match_day => same min datetime lock.

    Fallback order when match_day is missing/blank:
    1) stato_avanzamento_torneo
    2) individual match datetime
    """
    matches = matches.copy()
    if LOCK_TIMESTAMP_COL not in matches.columns:
        matches[LOCK_TIMESTAMP_COL] = ""
    if matches.empty or "datetime" not in matches.columns:
        return matches

    dt = parse_datetime_series(matches["datetime"])
    lock_values = pd.Series([""] * len(matches), index=matches.index, dtype="object")

    if MATCH_DAY_COL in matches.columns:
        match_days = matches[MATCH_DAY_COL].fillna("").astype(str).str.strip()
    else:
        match_days = pd.Series([""] * len(matches), index=matches.index)

    # Primary rule: all rows with the same match_day lock at the first datetime of that match_day.
    for match_day in sorted([x for x in match_days.unique().tolist() if x != ""]):
        mask = match_days == match_day
        dates = dt[mask].dropna()
        if not dates.empty:
            lock_values.loc[mask] = format_datetime_value(dates.min())

    # Fallback for rows without match_day: group by stage if present.
    remaining = lock_values == ""
    if remaining.any() and STAGE_COL in matches.columns:
        stages = matches[STAGE_COL].fillna("").astype(str).str.strip()
        for stage in sorted([x for x in stages[remaining].unique().tolist() if x != ""]):
            mask = remaining & (stages == stage)
            dates = dt[mask].dropna()
            if not dates.empty:
                lock_values.loc[mask] = format_datetime_value(dates.min())

    # Last fallback: single-match datetime.
    remaining = lock_values == ""
    if remaining.any():
        lock_values.loc[remaining] = dt[remaining].apply(format_datetime_value)

    matches[LOCK_TIMESTAMP_COL] = lock_values
    return matches


def normalize_scorer(value) -> str:
    value = clean_value(value)
    if value.upper() in ["OG", "AUTOGOL", "OWN GOAL"]:
        return ""
    return value


def normalize_scorers_list(value) -> str:
    value = clean_value(value)
    if value == "":
        return ""
    scorers = []
    for item in value.split(";"):
        scorer = normalize_scorer(item)
        if scorer != "":
            scorers.append(scorer)
    return ";".join(scorers)

def read_md_players() -> pd.DataFrame:
    players = read_csv(MD_PLAYERS_PATH)

    required_cols = {"team", "player_id", "player_name"}
    if players.empty or not required_cols.issubset(players.columns):
        return pd.DataFrame(columns=["team", "player_id", "player_name"])

    players = players[["team", "player_id", "player_name"]].copy()
    players["team"] = players["team"].apply(clean_value)
    players["player_id"] = players["player_id"].apply(clean_value)
    players["player_name"] = players["player_name"].apply(clean_value)

    players = players[
        players["team"].ne("")
        & players["player_id"].ne("")
        & players["player_name"].ne("")
    ].copy()

    return players.sort_values(["team", "player_name"]).reset_index(drop=True)


def get_match_teams(matches: pd.DataFrame, match_id) -> tuple[str, str]:
    if matches.empty or "match_id" not in matches.columns:
        return "", ""

    row = matches[matches["match_id"].astype(int) == int(match_id)]

    if row.empty:
        return "", ""

    home_team = clean_value(row.iloc[0].get("home_team", ""))
    away_team = clean_value(row.iloc[0].get("away_team", ""))

    return home_team, away_team


def player_options_for_team(md_players: pd.DataFrame, team: str) -> list[str]:
    team = clean_value(team)

    if md_players.empty or team == "":
        return []

    options = (
        md_players[md_players["team"] == team]["player_name"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .sort_values()
        .tolist()
    )

    return options


def append_scorer_to_list(current_scorers: str, new_scorer: str) -> str:
    current_scorers = normalize_scorers_list(current_scorers)
    new_scorer = normalize_scorer(new_scorer)

    if new_scorer == "":
        return current_scorers

    existing = [
        clean_value(x)
        for x in current_scorers.split(";")
        if clean_value(x) != ""
    ]

    if new_scorer not in existing:
        existing.append(new_scorer)

    return ";".join(existing)


def normalize_predictions_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "participant" in df.columns and "partecipant" not in df.columns:
        df = df.rename(columns={"participant": "partecipant"})
    for col in ["partecipant", "pred_home_score", "pred_away_score", "pred_result", "pred_scorer", "last_update"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(clean_value).astype("object")
    for col in [PRED_OG_1, PRED_OG_2]:
        if col not in df.columns:
            df[col] = False
        df[col] = clean_bool_series(df[col])
    if "match_id" in df.columns and not df.empty:
        df["match_id"] = df["match_id"].astype(int)
    return df


def normalize_matches_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in [STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_score", "away_score", "real_scorers"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(clean_value).astype("object")
    for col in [REAL_OG_1, REAL_OG_2]:
        if col not in df.columns:
            df[col] = False
        df[col] = clean_bool_series(df[col])
    if "match_id" in df.columns and not df.empty:
        df["match_id"] = df["match_id"].astype(int)
    return add_lock_timestamps(df)


def clean_result_value(value) -> str:
    return clean_value(value).upper()


def to_int_or_none(value):
    value = clean_value(value)
    if value == "":
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def calc_result(home_score, away_score) -> str:
    home = to_int_or_none(home_score)
    away = to_int_or_none(away_score)
    if home is None or away is None:
        return ""
    return "1" if home > away else "2" if home < away else "X"


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def commit_suffix() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_display_df(df: pd.DataFrame, message_if_empty: str) -> None:
    if df is None or df.empty:
        st.info(message_if_empty)
    else:
        st.dataframe(df, width="stretch")


def filter_dataframe(df: pd.DataFrame, key_prefix: str, label: str = "Filtri") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    filtered = df.copy()
    with st.expander(label, expanded=False):
        st.caption("Puoi filtrare qualsiasi colonna visibile nella tabella.")
        default_filters = [c for c in [MATCH_DAY_COL, STAGE_COL] if c in filtered.columns]
        filter_cols = st.multiselect(
            "Colonne da filtrare",
            options=list(filtered.columns),
            default=default_filters[:1],
            key=f"{key_prefix}_filter_cols",
        )
        for col in filter_cols:
            series = filtered[col].fillna("").astype(str)
            unique_values = sorted([x for x in series.unique().tolist() if x != ""])
            if 0 < len(unique_values) <= 60:
                selected_values = st.multiselect(f"Filtro {col}", unique_values, key=f"{key_prefix}_{col}_values")
                if selected_values:
                    filtered = filtered[filtered[col].fillna("").astype(str).isin(selected_values)]
            else:
                text_filter = st.text_input(f"Contiene in {col}", key=f"{key_prefix}_{col}_text")
                if text_filter:
                    filtered = filtered[filtered[col].fillna("").astype(str).str.contains(text_filter, case=False, na=False)]
    return filtered


def exact_score_correct(row) -> bool:
    pred_home = to_int_or_none(row.get("pred_home_score"))
    pred_away = to_int_or_none(row.get("pred_away_score"))
    real_home = to_int_or_none(row.get("home_score"))
    real_away = to_int_or_none(row.get("away_score"))
    if None in [pred_home, pred_away, real_home, real_away]:
        return False
    return pred_home == real_home and pred_away == real_away


def result_1x2_correct(row) -> bool:
    pred_result = clean_result_value(row.get("pred_result")) or calc_result(row.get("pred_home_score"), row.get("pred_away_score"))
    real_result = calc_result(row.get("home_score"), row.get("away_score"))
    return pred_result != "" and pred_result == real_result

def scorer_correct(row) -> bool:
    pred_scorer = normalize_scorer(row.get("pred_scorer"))
    real_scorers = normalize_scorers_list(row.get("real_scorers"))

    if pred_scorer == "" and real_scorers == "":
        return True

    if pred_scorer == "" or real_scorers == "":
        return False

    return pred_scorer.lower() in [
        clean_value(x).lower()
        for x in real_scorers.split(";")
        if clean_value(x) != ""
    ]


def own_goal_correct(row) -> bool:
    pred_og_1 = bool_value(row.get(PRED_OG_1))
    pred_og_2 = bool_value(row.get(PRED_OG_2))
    real_og_1 = bool_value(row.get(REAL_OG_1))
    real_og_2 = bool_value(row.get(REAL_OG_2))

    return (pred_og_1 and real_og_1) or (pred_og_2 and real_og_2)


def score_row(row) -> pd.Series:
    exact = exact_score_correct(row)
    result = result_1x2_correct(row)
    scorer = scorer_correct(row)
    own_goal = own_goal_correct(row)

    exact_points = POINTS_EXACT_SCORE if exact else 0
    result_points = POINTS_1X2 if result else 0
    scorer_points = POINTS_SCORER if scorer else 0
    own_goal_points = POINTS_OWN_GOAL if own_goal else 0

    return pd.Series({
        "exact_score_points": exact_points,
        "result_1x2_points": result_points,
        "scorer_points": scorer_points,
        "own_goal_points": own_goal_points,
        "total_points": exact_points + result_points + scorer_points + own_goal_points,
    })


def scoring_columns() -> list[str]:
    return [
        "partecipant", "match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team",
        "home_score", "away_score", "real_scorers", REAL_OG_1, REAL_OG_2,
        "pred_home_score", "pred_away_score", "pred_result", "pred_scorer", PRED_OG_1, PRED_OG_2,
        "exact_score_points", "result_1x2_points", "scorer_points", "own_goal_points", "total_points",
    ]


def run_scoring() -> tuple[pd.DataFrame, pd.DataFrame]:
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    predictions = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
    if matches.empty:
        raise ValueError("matches.csv non trovato o vuoto.")
    if predictions.empty:
        raise ValueError("predictions.csv non trovato o vuoto.")
    required_matches = {"match_id", "home_score", "away_score", "real_scorers", REAL_OG_1, REAL_OG_2}
    required_predictions = {"partecipant", "match_id", "pred_home_score", "pred_away_score", "pred_result", "pred_scorer", PRED_OG_1, PRED_OG_2}
    if required_matches - set(matches.columns):
        raise ValueError(f"matches.csv manca colonne: {required_matches - set(matches.columns)}")
    if required_predictions - set(predictions.columns):
        raise ValueError(f"predictions.csv manca colonne: {required_predictions - set(predictions.columns)}")
    df = predictions.merge(matches, on="match_id", how="left", suffixes=("_pred", "_real"))
    df = df[df["home_score"].astype(str).str.strip().ne("") & df["away_score"].astype(str).str.strip().ne("")].copy()
    if df.empty:
        save_empty_csv_and_push(PLAYER_POINTS_PATH, scoring_columns(), f"Reset player_points - {commit_suffix()}")
        empty_standings_cols = ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "correct_own_goals", "matches_scored"]
        save_empty_csv_and_push(STANDINGS_PATH, empty_standings_cols, f"Reset standings - {commit_suffix()}")
        return pd.DataFrame(columns=scoring_columns()), pd.DataFrame(columns=empty_standings_cols)
    player_points = pd.concat([df, df.apply(score_row, axis=1)], axis=1)
    player_points = player_points[[c for c in scoring_columns() if c in player_points.columns]]
    standings = player_points.groupby("partecipant", as_index=False).agg(
              total_points=("total_points", "sum"),
              exact_scores=("exact_score_points", lambda x: (x > 0).sum()),
              correct_1x2=("result_1x2_points", lambda x: (x > 0).sum()),
              correct_scorers=("scorer_points", lambda x: (x > 0).sum()),
              correct_own_goals=("own_goal_points", lambda x: (x > 0).sum()),
              matches_scored=("match_id", "count"),
              )
    standings = standings.sort_values(
               by=["total_points", "exact_scores", "correct_scorers", "correct_own_goals", "correct_1x2"],
               ascending=[False, False, False, False, False],
               ).reset_index(drop=True)
    standings.insert(0, "rank", range(1, len(standings) + 1))
    save_csv_and_push(player_points, PLAYER_POINTS_PATH, f"Update player_points - {commit_suffix()}")
    save_csv_and_push(standings, STANDINGS_PATH, f"Update standings - {commit_suffix()}")
    return player_points, standings


def create_backup() -> Path:
    ensure_data_dir()
    backup_path = BACKUP_DIR / f"backup_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path.mkdir(parents=True, exist_ok=True)
    for source in CSV_FILES:
        try:
            sync_file_from_github(source)
        except Exception:
            pass
        if source.exists():
            dest = backup_path / source.name
            shutil.copy2(source, dest)
            if github_enabled():
                github_put_file(repo_path(dest), dest.read_text(encoding="utf-8"), f"Create backup {backup_path.name} - {source.name}")
    return backup_path


def list_backups() -> list[Path]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if github_enabled():
        try:
            items = github_list_directory("data/backups")
            names = [i["name"] for i in items if i.get("type") == "dir" and i.get("name", "").startswith("backup_")]
            for name in names:
                (BACKUP_DIR / name).mkdir(parents=True, exist_ok=True)
            return sorted([BACKUP_DIR / n for n in names], reverse=True)
        except Exception:
            pass
    return sorted([p for p in BACKUP_DIR.iterdir() if p.is_dir() and p.name.startswith("backup_")], reverse=True)


def sync_backup_dir_from_github(backup_path: Path) -> None:
    if not github_enabled():
        return
    for item in github_list_directory(repo_path(backup_path)):
        if item.get("type") == "file":
            content, _ = github_get_file(item["path"])
            if content is not None:
                backup_path.mkdir(parents=True, exist_ok=True)
                (backup_path / item["name"]).write_text(content, encoding="utf-8")


def restore_backup(backup_path: Path) -> int:
    sync_backup_dir_from_github(backup_path)
    restored = 0
    for file_path in backup_path.glob("*.csv"):
        dest = DATA_DIR / file_path.name
        shutil.copy2(file_path, dest)
        restored += 1
        if github_enabled():
            github_put_file(repo_path(dest), dest.read_text(encoding="utf-8"), f"Restore {file_path.name} from {backup_path.name}")
    return restored


def reset_tournament() -> None:
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    if not matches.empty:
        for col in ["home_score", "away_score", "real_scorers", REAL_OG_1, REAL_OG_2]:
            if col in matches.columns:
                matches[col] = False if col in [REAL_OG_1, REAL_OG_2] else ""
        save_csv_and_push(matches, MATCHES_PATH, f"Reset matches results - {commit_suffix()}")
    predictions = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
    if not predictions.empty:
        for col in ["pred_home_score", "pred_away_score", "pred_result", "pred_scorer", "last_update", PRED_OG_1, PRED_OG_2]:
            if col in predictions.columns:
                predictions[col] = False if col in [PRED_OG_1, PRED_OG_2] else ""
        save_csv_and_push(predictions, PREDICTIONS_PATH, f"Reset predictions - {commit_suffix()}")
    save_empty_csv_and_push(PLAYER_POINTS_PATH, scoring_columns(), f"Reset player_points - {commit_suffix()}")
    save_empty_csv_and_push(STANDINGS_PATH, ["rank", "partecipant", "total_points", "exact_scores", "correct_1x2", "correct_scorers", "correct_own_goals", "matches_scored"], f"Reset standings - {commit_suffix()}")


def init_predictions() -> pd.DataFrame:
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    partecipants = read_csv(PARTECIPANTS_PATH)
    if matches.empty:
        raise ValueError("matches.csv non trovato o vuoto.")
    if partecipants.empty:
        raise ValueError("partecipants.csv non trovato o vuoto.")
    if "match_id" not in matches.columns:
        raise ValueError("matches.csv deve contenere la colonna match_id.")
    if "partecipant" not in partecipants.columns:
        raise ValueError("partecipants.csv deve contenere la colonna partecipant.")
    names = sorted(set(x for x in partecipants["partecipant"].dropna().astype(str).str.strip() if x != ""))
    rows = []
    for partecipant in names:
        for match_id in matches["match_id"].tolist():
            rows.append({"partecipant": partecipant, "match_id": int(match_id), "pred_home_score": "", "pred_away_score": "", "pred_result": "", "pred_scorer": "", PRED_OG_1: False, PRED_OG_2: False, "last_update": ""})
    new_df = pd.DataFrame(rows)
    if PREDICTIONS_PATH.exists():
        old_df = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
        keep = ["partecipant", "match_id", "pred_home_score", "pred_away_score", "pred_result", "pred_scorer", PRED_OG_1, PRED_OG_2, "last_update"]
        if {"partecipant", "match_id"}.issubset(old_df.columns):
            merged = new_df.merge(old_df[[c for c in keep if c in old_df.columns]], on=["partecipant", "match_id"], how="left", suffixes=("", "_old"))
            for col in ["pred_home_score", "pred_away_score", "pred_result", "pred_scorer", PRED_OG_1, PRED_OG_2, "last_update"]:
                old_col = f"{col}_old"
                if old_col in merged.columns:
                    merged[col] = merged[old_col].combine_first(merged[col])
                    merged = merged.drop(columns=[old_col])
            new_df = merged[keep]
    new_df = normalize_predictions_df(new_df)
    save_csv_and_push(new_df, PREDICTIONS_PATH, f"Initialize predictions - {commit_suffix()}")
    return new_df


def prepare_predictions_editor_view(view: pd.DataFrame) -> pd.DataFrame:
    view = normalize_predictions_df(view)
    for col in ["pred_scorer", "last_update", "home_team", "away_team", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "datetime"]:
        if col in view.columns:
            view[col] = view[col].fillna("").astype(str).replace("nan", "")
    for col in ["pred_home_score", "pred_away_score"]:
        if col in view.columns:
            view[col] = view[col].apply(to_int_or_none)
    return view


def prepare_results_editor_view(view: pd.DataFrame) -> pd.DataFrame:
    view = normalize_matches_df(view)
    for col in [STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "real_scorers", "home_team", "away_team", "group", "datetime"]:
        if col in view.columns:
            view[col] = view[col].fillna("").astype(str).replace("nan", "")
    for col in ["home_score", "away_score"]:
        if col in view.columns:
            view[col] = view[col].apply(to_int_or_none)
    return view


def save_current_matches(matches: pd.DataFrame) -> None:
    save_csv_and_push(normalize_matches_df(matches), MATCHES_PATH, f"Update match schema/results - {commit_suffix()}")


def save_current_predictions(predictions: pd.DataFrame) -> None:
    save_csv_and_push(normalize_predictions_df(predictions), PREDICTIONS_PATH, f"Update prediction schema/data - {commit_suffix()}")

def get_team_flag_map() -> dict:
    mapping = read_csv(TEAM_MAPPING_PATH)

    if mapping.empty:
        return {}

    if not {"team_name", "team_flag"}.issubset(mapping.columns):
        return {}

    mapping["team_name"] = mapping["team_name"].fillna("").astype(str).str.strip()
    mapping["team_flag"] = mapping["team_flag"].fillna("").astype(str).str.strip()

    return dict(zip(mapping["team_name"], mapping["team_flag"]))


def team_label(team_name, flag_map: dict) -> str:
    team_name = clean_value(team_name)

    if team_name == "":
        return ""

    for flag in flag_map.values():
        if flag and team_name.startswith(f"{flag} "):
            return team_name

    flag = clean_value(flag_map.get(team_name, ""))

    if flag == "":
        return team_name

    return f"{flag} {team_name}"


def add_team_flags(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    if "home_team" not in df.columns and "away_team" not in df.columns:
        return df

    df = df.copy()
    flag_map = get_team_flag_map()

    if "home_team" in df.columns:
        df["home_team"] = df["home_team"].apply(lambda x: team_label(x, flag_map))

    if "away_team" in df.columns:
        df["away_team"] = df["away_team"].apply(lambda x: team_label(x, flag_map))

    return df


def team_columns_config(extra: dict | None = None) -> dict:
    cfg = dict(extra or {})

    cfg.setdefault(
        "home_team",
        st.column_config.TextColumn("Casa", width="medium"),
    )

    cfg.setdefault(
        "away_team",
        st.column_config.TextColumn("Trasferta", width="medium"),
    )

    return cfg


ensure_data_dir()
if "synced_once" not in st.session_state:
    sync_core_files_from_github()
    st.session_state["synced_once"] = True

current_user = login_box(USERS_PATH)
is_admin = user_is_admin(current_user)
current_partecipant = clean_value(current_user.get("partecipant", "")) if current_user else ""

st.title("⚙️ INNIAREBACK - Backend Mondiali 2026")

with st.sidebar:
    st.title("Menu")
    st.caption(f"Utente: {clean_value(current_user.get('username', ''))}")
    st.caption(f"Ruolo: {'admin' if is_admin else 'user'}")
    logout_button()
    if github_enabled():
        st.success("GitHub persistence attiva")
    else:
        st.warning("GitHub persistence non configurata")
    admin_pages = ["📊 Dashboard", "📅 Calendario", "✏️ Pronostici", "⚽ Risultati reali", "🏆 Classifica", "🛠️ Amministrazione"]
    user_pages = ["📊 Dashboard", "📅 Calendario", "✏️ Pronostici", "🏆 Classifica"]
    page = st.radio("Sezione", admin_pages if is_admin else user_pages)

if page == "📊 Dashboard":
    st.header("📊 Dashboard")
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    predictions = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
    standings = read_csv(STANDINGS_PATH)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Partite", 0 if matches.empty else len(matches))
    with c2:
        finished = 0 if matches.empty else (matches["home_score"].astype(str).str.strip().ne("") & matches["away_score"].astype(str).str.strip().ne("")).sum()
        st.metric("Partite concluse", int(finished))
    with c3:
        st.metric("Partecipanti", 0 if predictions.empty or "partecipant" not in predictions.columns else predictions["partecipant"].nunique())
    with c4:
        updated = 0 if predictions.empty or "last_update" not in predictions.columns else (predictions["last_update"].astype(str).str.strip().ne("")).sum()
        st.metric("Pronostici compilati", int(updated))
    st.divider()
    safe_display_df(standings, "Classifica non ancora calcolata.")

elif page == "📅 Calendario":
    st.header("📅 Calendario")
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    if matches.empty:
        st.warning("matches.csv non trovato o vuoto.")
    else:
        if MATCH_DAY_COL not in matches.columns or LOCK_TIMESTAMP_COL not in matches.columns:
            save_current_matches(matches)
            st.info("Schema matches aggiornato con match_day/lock_timestamp. Ricarico la pagina.")
            st.rerun()
        view = filter_dataframe(matches.copy(), "calendar", "Filtri calendario")
        view = add_team_flags(view)
        st.dataframe(
        view,
        width="stretch",
        column_config=team_columns_config(),
        )

elif page == "✏️ Pronostici":
    st.header("✏️ Inserimento pronostici")
    predictions = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    md_players = read_md_players()
    if predictions.empty:
        st.warning("predictions.csv non trovato o vuoto.")
        if is_admin and st.button("Inizializza predictions.csv"):
            try:
                df_init = init_predictions()
                st.success(f"predictions.csv creato/aggiornato: {len(df_init)} righe.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    elif matches.empty:
        st.warning("matches.csv non trovato o vuoto.")
    elif "partecipant" not in predictions.columns:
        st.error("predictions.csv deve contenere la colonna partecipant.")
    else:
        if not {PRED_OG_1, PRED_OG_2}.issubset(predictions.columns):
            save_current_predictions(predictions)
            st.info("Schema predictions aggiornato con le colonne autogol. Ricarico la pagina.")
            st.rerun()
        if MATCH_DAY_COL not in matches.columns or STAGE_COL not in matches.columns or LOCK_TIMESTAMP_COL not in matches.columns:
            save_current_matches(matches)
            st.info("Schema matches aggiornato con stato/match_day/lock_timestamp. Ricarico la pagina.")
            st.rerun()

        partecipants = sorted(predictions["partecipant"].dropna().astype(str).unique())
        selected_partecipant = current_partecipant
        st.info(f"Stai inserendo i pronostici come: {selected_partecipant}")
        if selected_partecipant not in partecipants:
            st.error("Il tuo utente non è associato a un partecipante presente in predictions.csv.")
            st.stop()

        df_user = predictions[predictions["partecipant"].astype(str) == selected_partecipant].copy()
        match_info_cols = [c for c in ["match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team"] if c in matches.columns]
        view = df_user.merge(matches[match_info_cols], on="match_id", how="left")
        editable_cols = [c for c in ["match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team", "pred_home_score", "pred_away_score", "pred_scorer", PRED_OG_1, PRED_OG_2, "last_update"] if c in view.columns]
        view = prepare_predictions_editor_view(view)
        view = filter_dataframe(view, "predictions", "Filtri pronostici")
        view["locked"] = view[LOCK_TIMESTAMP_COL].apply(is_locked_value)
        unlocked_view = view[~view["locked"]].copy()
        locked_view = view[view["locked"]].copy()
        unlocked_view = add_team_flags(unlocked_view)
        locked_view = add_team_flags(locked_view)

        st.caption("Il lock_timestamp è calcolato per match_day: tutte le righe con lo stesso match_day si bloccano all'inizio della prima partita di quel match day.")
        if md_players.empty:
           st.warning("md_players.csv non trovato o non valido: il marcatore resta inseribile manualmente.")
        else:
           with st.expander("🎯 Selezione marcatore da rosa", expanded=False):
             st.caption("Seleziona partita, squadra e giocatore. La scelta aggiorna il campo pred_scorer del pronostico.")

             available_matches = unlocked_view.copy()

             if available_matches.empty:
                st.info("Nessuna partita modificabile per il drilldown marcatori.")
             else:
                available_matches["match_label"] = available_matches.apply(
                  lambda r: f'{int(r["match_id"])} - {clean_value(r.get("home_team", ""))} vs {clean_value(r.get("away_team", ""))}',
                  axis=1,
                 )

                match_labels = available_matches["match_label"].tolist()
                selected_match_label = st.selectbox(
                  "Partita",
                  match_labels,
                  key=f"pred_scorer_match_{selected_partecipant}",
                 )

                selected_match_id = int(selected_match_label.split(" - ")[0])
                home_team, away_team = get_match_teams(matches, selected_match_id)

                team_choice = st.radio(
                  "Squadra",
                  [home_team, away_team],
                  horizontal=True,
                  key=f"pred_scorer_team_{selected_partecipant}_{selected_match_id}",
                 )

                 player_options = ["-- Nessun marcatore --"] + player_options_for_team(md_players, team_choice)

                 selected_player = st.selectbox(
                  "Marcatore",
                  player_options,
                  key=f"pred_scorer_player_{selected_partecipant}_{selected_match_id}",
                  )

                 c1, c2 = st.columns(2)

                 with c1:
                   if st.button("✅ Applica marcatore al pronostico", key=f"apply_pred_scorer_{selected_partecipant}_{selected_match_id}"):
                      mask = (
                          (predictions["partecipant"].astype(str) == selected_partecipant)
                          & (predictions["match_id"].astype(int) == selected_match_id)
                       )

                      if selected_player == "-- Nessun marcatore --":
                          predictions.loc[mask, "pred_scorer"] = ""
                      else:
                          predictions.loc[mask, "pred_scorer"] = selected_player
                          predictions.loc[mask, PRED_OG_1] = False
                          predictions.loc[mask, PRED_OG_2] = False

                      predictions.loc[mask, "last_update"] = now_string()
                      save_current_predictions(predictions)
                      st.success("Marcatore pronostico aggiornato.")
                      st.rerun()

                 with c2:
                  if st.button("🧹 Svuota marcatore", key=f"clear_pred_scorer_{selected_partecipant}_{selected_match_id}"):
                      mask = (
                          (predictions["partecipant"].astype(str) == selected_partecipant)
                          & (predictions["match_id"].astype(int) == selected_match_id)
                       )

                      predictions.loc[mask, "pred_scorer"] = ""
                      predictions.loc[mask, "last_update"] = now_string()
                      save_current_predictions(predictions)
                      st.success("Marcatore pronostico svuotato.")
                      st.rerun()
                    
        if not unlocked_view.empty:
            edited = st.data_editor(
                unlocked_view[[c for c in editable_cols if c in unlocked_view.columns]],
                width="stretch",
                num_rows="fixed",
                disabled=[c for c in ["match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team", "last_update"] if c in editable_cols],
                column_config={
                    "pred_home_score": st.column_config.NumberColumn("Gol Casa", min_value=0, step=1, format="%d"),
                    "pred_away_score": st.column_config.NumberColumn("Gol Trasferta", min_value=0, step=1, format="%d"),
                    "pred_scorer": st.column_config.TextColumn("Marcatore", help="Non usare OG/autogol: usa i flag dedicati."),
                    PRED_OG_1: st.column_config.CheckboxColumn("Autogol squadra 1"),
                    PRED_OG_2: st.column_config.CheckboxColumn("Autogol squadra 2"),
                    "last_update": st.column_config.TextColumn("Ultimo aggiornamento"),
                },
                key=f"pred_editor_{selected_partecipant}",
            )
            if st.button("💾 Salva pronostici"):
                now = now_string()
                predictions = normalize_predictions_df(predictions)
                both_flags_count = 0
                scorer_cleared_count = 0
                for _, row in edited.iterrows():
                    match_id = int(row["match_id"])
                    match_lock = matches.loc[matches["match_id"].astype(int) == match_id, LOCK_TIMESTAMP_COL]
                    if not match_lock.empty and is_locked_value(match_lock.iloc[0]):
                        continue
                    mask = (predictions["partecipant"].astype(str) == selected_partecipant) & (predictions["match_id"].astype(int) == match_id)
                    pred_home = clean_value(row.get("pred_home_score", ""))
                    pred_away = clean_value(row.get("pred_away_score", ""))
                    og1 = bool_value(row.get(PRED_OG_1))
                    og2 = bool_value(row.get(PRED_OG_2))
                    if og1 and og2:
                        og2 = False
                        both_flags_count += 1
                    pred_scorer = normalize_scorer(row.get("pred_scorer", ""))
                    if og1 or og2:
                        if pred_scorer != "":
                            scorer_cleared_count += 1
                        pred_scorer = ""
                    predictions.loc[mask, "pred_home_score"] = pred_home
                    predictions.loc[mask, "pred_away_score"] = pred_away
                    predictions.loc[mask, "pred_scorer"] = pred_scorer
                    predictions.loc[mask, PRED_OG_1] = og1
                    predictions.loc[mask, PRED_OG_2] = og2
                    predictions.loc[mask, "pred_result"] = calc_result(pred_home, pred_away)
                    predictions.loc[mask, "last_update"] = now if (pred_home or pred_away or pred_scorer or og1 or og2) else ""
                save_current_predictions(predictions)
                if both_flags_count:
                    st.warning(f"In {both_flags_count} riga/e erano flaggate entrambe le squadre: ho mantenuto solo Autogol squadra 1.")
                if scorer_cleared_count:
                    st.warning(f"In {scorer_cleared_count} riga/e il marcatore è stato svuotato perché era presente un flag autogol.")
                st.success("Pronostici salvati su GitHub.")
                st.rerun()
        else:
            st.info("Non ci sono pronostici modificabili con i filtri correnti: tutti i match day visualizzati sono già bloccati oppure non ci sono righe.")

        if not locked_view.empty:
            st.subheader("Pronostici tuoi bloccati")
            st.dataframe(locked_view[[c for c in editable_cols if c in locked_view.columns]], width="stretch")

        st.divider()
        st.subheader("Pronostici visibili dopo blocco")
        all_predictions = normalize_predictions_df(read_csv(PREDICTIONS_PATH))
        visible = all_predictions.merge(matches[match_info_cols], on="match_id", how="left")
        visible["locked"] = visible[LOCK_TIMESTAMP_COL].apply(is_locked_value)
        visible = visible[visible["locked"]].copy()
        if visible.empty:
            st.info("Nessun pronostico visibile: i match day non sono ancora arrivati al lock_timestamp.")
        else:
            show_cols = [c for c in ["partecipant", "match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team", "pred_home_score", "pred_away_score", "pred_scorer", PRED_OG_1, PRED_OG_2, "last_update"] if c in visible.columns]
            visible = filter_dataframe(visible[show_cols], "visible_predictions", "Filtri pronostici visibili")
            st.dataframe(visible, width="stretch")

elif page == "⚽ Risultati reali":
    if not is_admin:
        st.error("Sezione riservata agli admin.")
        st.stop()
    st.header("⚽ Inserimento risultati reali")
    matches = normalize_matches_df(read_csv(MATCHES_PATH))
    md_players = read_md_players()
    if matches.empty:
        st.warning("matches.csv non trovato o vuoto.")
    else:
        if not {REAL_OG_1, REAL_OG_2}.issubset(matches.columns) or MATCH_DAY_COL not in matches.columns or STAGE_COL not in matches.columns or LOCK_TIMESTAMP_COL not in matches.columns:
            save_current_matches(matches)
            st.info("Schema matches aggiornato con colonne stato/match_day/lock/autogol. Ricarico la pagina.")
            st.rerun()
        edit_cols = [c for c in ["match_id", "datetime", "group", STAGE_COL, MATCH_DAY_COL, LOCK_TIMESTAMP_COL, "home_team", "away_team", "home_score", "away_score", "real_scorers", REAL_OG_1, REAL_OG_2] if c in matches.columns]
        view = prepare_results_editor_view(matches[edit_cols])
        view = filter_dataframe(view, "real_results", "Filtri risultati reali")
        edited = st.data_editor(
            view,
            width="stretch",
            num_rows="fixed",
            disabled=[c for c in ["match_id", "datetime", "group", LOCK_TIMESTAMP_COL, "home_team", "away_team"] if c in edit_cols],
            column_config={
                STAGE_COL: st.column_config.TextColumn("Stato avanzamento torneo", help="Es. Giornata 1, Giornata 2, Giornata 3, Ottavi, Quarti..."),
                MATCH_DAY_COL: st.column_config.TextColumn("Match day", help="Valore che raggruppa le partite con stesso lock. Es. 1, 2, 3, Ottavi-1..."),
                LOCK_TIMESTAMP_COL: st.column_config.TextColumn("Lock timestamp", help="Calcolato automaticamente come minimo datetime del match_day."),
                "home_score": st.column_config.NumberColumn("Gol Casa", min_value=0, step=1, format="%d"),
                "away_score": st.column_config.NumberColumn("Gol Trasferta", min_value=0, step=1, format="%d"),
                "real_scorers": st.column_config.TextColumn("Marcatori reali", help="Separali con ;. Non usare OG/autogol: usa i flag dedicati."),
                REAL_OG_1: st.column_config.CheckboxColumn("Autogol squadra 1 reale"),
                REAL_OG_2: st.column_config.CheckboxColumn("Autogol squadra 2 reale"),
                "home_team": st.column_config.TextColumn("Casa", width="medium"),
                "away_team": st.column_config.TextColumn("Trasferta", width="medium"),
            },
            key="real_results_editor",
        )

        if md_players.empty:
            st.warning("md_players.csv non trovato o non valido: i marcatori reali restano inseribili manualmente.")
        else:
            with st.expander("⚽ Inserimento marcatori reali da rosa", expanded=False):
              st.caption("Seleziona partita, squadra e giocatore. Puoi aggiungere più marcatori: verranno separati con ;")

              scorer_matches = view.copy()

              if scorer_matches.empty:
                 st.info("Nessuna partita disponibile per il drilldown marcatori reali.")
              else:
                 scorer_matches["match_label"] = scorer_matches.apply(
                   lambda r: f'{int(r["match_id"])} - {clean_value(r.get("home_team", ""))} vs {clean_value(r.get("away_team", ""))}',
                   axis=1,
                  )

                 match_labels = scorer_matches["match_label"].tolist()

                 selected_real_match_label = st.selectbox(
                  "Partita",
                  match_labels,
                  key="real_scorer_match",
                  )

                 selected_real_match_id = int(selected_real_match_label.split(" - ")[0])
                 home_team, away_team = get_match_teams(matches, selected_real_match_id)

                 real_team_choice = st.radio(
                  "Squadra marcatrice",
                  [home_team, away_team],
                  horizontal=True,
                  key=f"real_scorer_team_{selected_real_match_id}",
                  )

                 real_player_options = ["-- Nessun marcatore --"] + player_options_for_team(md_players, real_team_choice)

                 selected_real_player = st.selectbox(
                  "Marcatore reale",
                  real_player_options,
                  key=f"real_scorer_player_{selected_real_match_id}",
                  )

                 c1, c2 = st.columns(2)

                 with c1:
                    if st.button("➕ Aggiungi marcatore reale", key=f"add_real_scorer_{selected_real_match_id}"):
                       current_matches = normalize_matches_df(matches)
                       mask = current_matches["match_id"].astype(int) == selected_real_match_id

                       if selected_real_player != "-- Nessun marcatore --":
                          current_value = current_matches.loc[mask, "real_scorers"].iloc[0]
                          new_value = append_scorer_to_list(current_value, selected_real_player)
                          current_matches.loc[mask, "real_scorers"] = new_value
                          save_current_matches(current_matches)
                          st.success("Marcatore reale aggiunto.")
                          st.rerun()
                       else:
                          st.info("Nessun marcatore selezionato.")

                 with c2:
                    if st.button("🧹 Svuota marcatori reali partita", key=f"clear_real_scorers_{selected_real_match_id}"):
                       current_matches = normalize_matches_df(matches)
                       mask = current_matches["match_id"].astype(int) == selected_real_match_id
                       current_matches.loc[mask, "real_scorers"] = ""
                       save_current_matches(current_matches)
                       st.success("Marcatori reali svuotati per la partita selezionata.")
                       st.rerun()

        def save_results_from_editor():
            current_matches = normalize_matches_df(matches)
            scorer_cleared_count = 0
            for _, row in edited.iterrows():
                match_id = int(row["match_id"])
                mask = current_matches["match_id"].astype(int) == match_id
                current_matches.loc[mask, STAGE_COL] = clean_value(row.get(STAGE_COL, ""))
                current_matches.loc[mask, MATCH_DAY_COL] = clean_value(row.get(MATCH_DAY_COL, ""))
                current_matches.loc[mask, "home_score"] = clean_value(row.get("home_score", ""))
                current_matches.loc[mask, "away_score"] = clean_value(row.get("away_score", ""))
                real_scorers_raw = clean_value(row.get("real_scorers", ""))
                real_scorers = normalize_scorers_list(real_scorers_raw)
                if real_scorers_raw != "" and real_scorers == "":
                    scorer_cleared_count += 1
                current_matches.loc[mask, "real_scorers"] = real_scorers
                current_matches.loc[mask, REAL_OG_1] = bool_value(row.get(REAL_OG_1))
                current_matches.loc[mask, REAL_OG_2] = bool_value(row.get(REAL_OG_2))
            save_current_matches(current_matches)
            if scorer_cleared_count:
                st.warning(f"In {scorer_cleared_count} riga/e OG/autogol è stato rimosso dai marcatori: usa i flag Autogol squadra 1/2 reale.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Salva risultati reali"):
                try:
                    save_results_from_editor()
                    st.success("Risultati reali salvati su GitHub.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with col2:
            if st.button("🏆 Salva e calcola classifica"):
                try:
                    save_results_from_editor()
                    _, standings = run_scoring()
                    if standings.empty:
                        st.warning("Nessuna partita con risultato reale completo.")
                    else:
                        st.success("Classifica calcolata e salvata su GitHub.")
                        st.dataframe(standings, width="stretch")
                except Exception as e:
                    st.error(str(e))

elif page == "🏆 Classifica":
    st.header("🏆 Classifica")
    if is_admin and st.button("🔄 Ricalcola classifica"):
        try:
            _, standings = run_scoring()
            if standings.empty:
                st.warning("Nessuna partita con risultato reale completo.")
            else:
                st.success("Classifica ricalcolata e salvata su GitHub.")
                st.rerun()
        except Exception as e:
            st.error(str(e))
    standings = read_csv(STANDINGS_PATH)
    safe_display_df(standings, "Classifica non ancora disponibile.")
    player_points = read_csv(PLAYER_POINTS_PATH)
    if not player_points.empty and "partecipant" in player_points.columns:
        st.subheader("Dettaglio punti partita per partita")
        if is_admin:
            partecipants = ["Tutti"] + sorted(player_points["partecipant"].dropna().astype(str).unique().tolist())
            selected = st.selectbox("Filtro partecipante", partecipants)
            view = player_points if selected == "Tutti" else player_points[player_points["partecipant"].astype(str) == selected]
        else:
            view = player_points[player_points["partecipant"].astype(str) == current_partecipant]
        view = add_team_flags(view)
        st.dataframe(
        view,
        width="stretch",
        column_config=team_columns_config(),
        )

elif page == "🛠️ Amministrazione":
    if not is_admin:
        st.error("Sezione riservata agli admin.")
        st.stop()
    st.header("🛠️ Amministrazione")
    st.subheader("Stato persistenza")
    if github_enabled():
        _, repo, branch = get_github_config()
        st.success(f"GitHub configurato: {repo} / branch {branch}")
    else:
        st.error("GitHub non configurato. Aggiungi GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH nei Secrets di Streamlit.")
    st.divider()
    st.subheader("Sync")
    if st.button("🔄 Sincronizza file core da GitHub"):
        sync_core_files_from_github()
        st.success("File core sincronizzati da GitHub.")
        st.rerun()
    st.divider()
    st.subheader("Rigenerazione predictions")
    if st.button("🔄 Rigenera predictions da partecipants.csv"):
        try:
            df_init = init_predictions()
            st.success(f"predictions.csv rigenerato: {len(df_init)} righe.")
            st.rerun()
        except Exception as e:
            st.error(str(e))
    st.divider()
    st.subheader("Backup / Restore / Reset")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("📦 Crea backup"):
            try:
                backup_path = create_backup()
                st.success(f"Backup creato: {backup_path.name}")
            except Exception as e:
                st.error(str(e))
    with c2:
        backups = list_backups()
        backup_names = [b.name for b in backups]
        if backup_names:
            selected_backup = st.selectbox("Backup da ripristinare", backup_names)
            if st.button("♻️ Ripristina backup"):
                try:
                    restored = restore_backup(BACKUP_DIR / selected_backup)
                    st.success(f"Backup ripristinato. File ripristinati: {restored}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        else:
            st.info("Nessun backup disponibile.")
    with c3:
        confirm = st.checkbox("Confermo reset completo")
        if st.button("🧨 Reset torneo"):
            if not confirm:
                st.warning("Spunta la conferma prima di resettare.")
            else:
                try:
                    create_backup()
                    reset_tournament()
                    st.success("Torneo resettato. Backup creato prima del reset.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    st.divider()
    st.subheader("File dati")
    files = sorted(DATA_DIR.glob("*.csv"))
    if not files:
        st.info("Nessun CSV trovato nella cartella data.")
    else:
        for path in files:
            df = read_csv(path, sync=False)
            st.write(f"**{path.name}** — {len(df)} righe")
