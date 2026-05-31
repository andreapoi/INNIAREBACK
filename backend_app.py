from pathlib import Path
from datetime import datetime
from io import StringIO
import base64
import shutil

import pandas as pd
import requests
import streamlit as st


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"

MATCHES_PATH = DATA_DIR / "matches.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
PARTECIPANTS_PATH = DATA_DIR / "partecipants.csv"
TEAM_MAPPING_PATH = DATA_DIR / "team_mapping.csv"
STANDINGS_PATH = DATA_DIR / "standings.csv"
PLAYER_POINTS_PATH = DATA_DIR / "player_points.csv"

POINTS_EXACT_SCORE = 5
POINTS_1X2 = 2
POINTS_SCORER = 3.5

CSV_FILES = [
    MATCHES_PATH,
    PREDICTIONS_PATH,
    PARTECIPANTS_PATH,
    TEAM_MAPPING_PATH,
    STANDINGS_PATH,
    PLAYER_POINTS_PATH,
]

st.set_page_config(
    page_title="INNIAREBACK Backend",
    page_icon="⚽",
    layout="wide",
)


# ============================================================
# GITHUB PERSISTENCE
# ============================================================

def github_enabled() -> bool:
    return (
        "GITHUB_TOKEN" in st.secrets
        and "GITHUB_REPO" in st.secrets
        and "GITHUB_BRANCH" in st.secrets
    )


def get_github_config():
    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    branch = st.secrets.get("GITHUB_BRANCH", "main")
    return token, repo, branch


def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_get_file(path_in_repo: str):
    token, repo, branch = get_github_config()

    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"

    response = requests.get(
        url,
        headers=github_headers(token),
        params={"ref": branch},
        timeout=30,
    )

    if response.status_code == 404:
        return None, None

    response.raise_for_status()

    payload = response.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")

    return content, payload["sha"]


def github_put_file(path_in_repo: str, content: str, message: str) -> None:
    token, repo, branch = get_github_config()

    _, sha = github_get_file(path_in_repo)

    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    payload = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(token),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()


def github_list_directory(path_in_repo: str) -> list[dict]:
    token, repo, branch = get_github_config()

    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"

    response = requests.get(
        url,
        headers=github_headers(token),
        params={"ref": branch},
        timeout=30,
    )

    if response.status_code == 404:
        return []

    response.raise_for_status()

    payload = response.json()

    if isinstance(payload, dict):
        return [payload]

    return payload


def repo_path(local_path: Path) -> str:
    return local_path.relative_to(BASE_DIR).as_posix()


def sync_file_from_github(local_path: Path) -> bool:
    if not github_enabled():
        return False

    path_in_repo = repo_path(local_path)
    content, _ = github_get_file(path_in_repo)

    if content is None:
        return False

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")

    return True


def sync_core_files_from_github() -> None:
    if not github_enabled():
        return

    for path in CSV_FILES:
        try:
            sync_file_from_github(path)
        except Exception:
            pass


def save_text_and_push(local_path: Path, content: str, commit_message: str) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")

    if github_enabled():
        github_put_file(
            path_in_repo=repo_path(local_path),
            content=content,
            message=commit_message,
        )
    else:
        st.warning(
            "GitHub non è configurato nei Secrets. "
            "Il file è stato salvato solo localmente e potrebbe non persistere."
        )


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def save_csv_and_push(df: pd.DataFrame, path: Path, commit_message: str) -> None:
    csv_content = df.to_csv(index=False)
    save_text_and_push(path, csv_content, commit_message)


# ============================================================
# GENERIC HELPERS
# ============================================================

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
        df = pd.read_csv(
            path,
            sep=None,
            engine="python",
            encoding="utf-8-sig",
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    return df


def clean_value(value) -> str:
    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    return value


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

    if home > away:
        return "1"
    if home < away:
        return "2"

    return "X"


def normalize_scorer(value) -> str:
    value = clean_value(value)

    if value.upper() in ["OG", "AUTOGOL", "OWN GOAL"]:
        return "OG"

    return value


def normalize_scorers_list(value) -> str:
    value = clean_value(value)

    if value == "":
        return ""

    parts = [
        normalize_scorer(x)
        for x in value.split(";")
        if clean_value(x) != ""
    ]

    return ";".join(parts)


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def commit_suffix() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# SCORING
# ============================================================

def exact_score_correct(row) -> bool:
    pred_home = to_int_or_none(row.get("pred_home_score"))
    pred_away = to_int_or_none(row.get("pred_away_score"))
    real_home = to_int_or_none(row.get("home_score"))
    real_away = to_int_or_none(row.get("away_score"))

    if None in [pred_home, pred_away, real_home, real_away]:
        return False

    return pred_home == real_home and pred_away == real_away


def result_1x2_correct(row) -> bool:
    pred_result = clean_result_value(row.get("pred_result"))

    if pred_result == "":
        pred_result = calc_result(
            row.get("pred_home_score"),
            row.get("pred_away_score"),
        )

    real_result = calc_result(
        row.get("home_score"),
        row.get("away_score"),
    )

    return pred_result != "" and pred_result == real_result


def scorer_correct(row) -> bool:
    pred_scorer = normalize_scorer(row.get("pred_scorer"))
    real_scorers = normalize_scorers_list(row.get("real_scorers"))

    if pred_scorer == "" and real_scorers == "":
        return True

    if pred_scorer != "" and real_scorers == "":
        return False

    if pred_scorer == "" and real_scorers != "":
        return False

    real_scorers_list = [
        clean_value(x).lower()
        for x in real_scorers.split(";")
        if clean_value(x) != ""
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


def run_scoring() -> tuple[pd.DataFrame, pd.DataFrame]:
    matches = read_csv(MATCHES_PATH)
    predictions = read_csv(PREDICTIONS_PATH)

    if matches.empty:
        raise ValueError("matches.csv non trovato o vuoto.")

    if predictions.empty:
        raise ValueError("predictions.csv non trovato o vuoto.")

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

    missing_matches = required_matches - set(matches.columns)
    missing_predictions = required_predictions - set(predictions.columns)

    if missing_matches:
        raise ValueError(f"matches.csv manca colonne: {missing_matches}")

    if missing_predictions:
        raise ValueError(f"predictions.csv manca colonne: {missing_predictions}")

    matches["match_id"] = matches["match_id"].astype(int)
    predictions["match_id"] = predictions["match_id"].astype(int)

    df = predictions.merge(
        matches,
        on="match_id",
        how="left",
        suffixes=("_pred", "_real"),
    )

    df = df[
        df["home_score"].notna()
        & df["away_score"].notna()
        & (df["home_score"].astype(str).str.strip() != "")
        & (df["away_score"].astype(str).str.strip() != "")
    ].copy()

    if df.empty:
        empty_points = pd.DataFrame()
        empty_standings = pd.DataFrame()
        save_csv_and_push(
            empty_points,
            PLAYER_POINTS_PATH,
            f"Reset player_points - {commit_suffix()}",
        )
        save_csv_and_push(
            empty_standings,
            STANDINGS_PATH,
            f"Reset standings - {commit_suffix()}",
        )
        return empty_points, empty_standings

    points = df.apply(score_row, axis=1)
    player_points = pd.concat([df, points], axis=1)

    keep_cols = [
        "partecipant",
        "match_id",
        "datetime",
        "group",
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

    keep_cols = [c for c in keep_cols if c in player_points.columns]
    player_points = player_points[keep_cols]

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
        by=[
            "total_points",
            "exact_scores",
            "correct_scorers",
            "correct_1x2",
        ],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    standings.insert(0, "rank", range(1, len(standings) + 1))

    save_csv_and_push(
        player_points,
        PLAYER_POINTS_PATH,
        f"Update player_points - {commit_suffix()}",
    )

    save_csv_and_push(
        standings,
        STANDINGS_PATH,
        f"Update standings - {commit_suffix()}",
    )

    return player_points, standings


# ============================================================
# BACKUP / RESTORE / RESET
# ============================================================

def create_backup() -> Path:
    ensure_data_dir()

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}"
    backup_path.mkdir(parents=True, exist_ok=True)

    copied = 0

    for source in CSV_FILES:
        if github_enabled():
            try:
                sync_file_from_github(source)
            except Exception:
                pass

        if source.exists():
            dest = backup_path / source.name
            shutil.copy2(source, dest)
            copied += 1

            if github_enabled():
                content = dest.read_text(encoding="utf-8")
                github_put_file(
                    path_in_repo=repo_path(dest),
                    content=content,
                    message=f"Create backup {backup_path.name} - {source.name}",
                )

    return backup_path


def list_backups() -> list[Path]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if github_enabled():
        try:
            items = github_list_directory("data/backups")
            backup_dirs = [
                item["name"]
                for item in items
                if item.get("type") == "dir" and item.get("name", "").startswith("backup_")
            ]

            for backup_name in backup_dirs:
                local_backup_dir = BACKUP_DIR / backup_name
                local_backup_dir.mkdir(parents=True, exist_ok=True)

            return sorted(
                [BACKUP_DIR / b for b in backup_dirs],
                reverse=True,
            )
        except Exception:
            pass

    return sorted(
        [
            p for p in BACKUP_DIR.iterdir()
            if p.is_dir() and p.name.startswith("backup_")
        ],
        reverse=True,
    )


def sync_backup_dir_from_github(backup_path: Path) -> None:
    if not github_enabled():
        return

    backup_repo_path = repo_path(backup_path)

    try:
        items = github_list_directory(backup_repo_path)
    except Exception:
        return

    backup_path.mkdir(parents=True, exist_ok=True)

    for item in items:
        if item.get("type") != "file":
            continue

        file_repo_path = item["path"]
        content, _ = github_get_file(file_repo_path)

        if content is None:
            continue

        local_file = backup_path / item["name"]
        local_file.write_text(content, encoding="utf-8")


def restore_backup(backup_path: Path) -> int:
    if github_enabled():
        sync_backup_dir_from_github(backup_path)

    restored = 0

    for file_path in backup_path.glob("*.csv"):
        dest = DATA_DIR / file_path.name
        shutil.copy2(file_path, dest)
        restored += 1

        if github_enabled():
            github_put_file(
                path_in_repo=repo_path(dest),
                content=dest.read_text(encoding="utf-8"),
                message=f"Restore {file_path.name} from {backup_path.name}",
            )

    return restored


def reset_tournament() -> None:
    matches = read_csv(MATCHES_PATH)

    if not matches.empty:
        for col in ["home_score", "away_score", "real_scorers"]:
            if col in matches.columns:
                matches[col] = ""

        save_csv_and_push(
            matches,
            MATCHES_PATH,
            f"Reset matches results - {commit_suffix()}",
        )

    predictions = read_csv(PREDICTIONS_PATH)

    if not predictions.empty:
        for col in [
            "pred_home_score",
            "pred_away_score",
            "pred_result",
            "pred_scorer",
            "last_update",
        ]:
            if col in predictions.columns:
                predictions[col] = ""

        save_csv_and_push(
            predictions,
            PREDICTIONS_PATH,
            f"Reset predictions - {commit_suffix()}",
        )

    save_csv_and_push(
        pd.DataFrame(),
        PLAYER_POINTS_PATH,
        f"Reset player_points - {commit_suffix()}",
    )

    save_csv_and_push(
        pd.DataFrame(),
        STANDINGS_PATH,
        f"Reset standings - {commit_suffix()}",
    )


# ============================================================
# INIT PREDICTIONS
# ============================================================

def init_predictions() -> pd.DataFrame:
    matches = read_csv(MATCHES_PATH)
    partecipants = read_csv(PARTECIPANTS_PATH)

    if matches.empty:
        raise ValueError("matches.csv non trovato o vuoto.")

    if partecipants.empty:
        raise ValueError("partecipants.csv non trovato o vuoto.")

    if "match_id" not in matches.columns:
        raise ValueError("matches.csv deve contenere la colonna match_id.")

    if "partecipant" not in partecipants.columns:
        raise ValueError("partecipants.csv deve contenere la colonna partecipant.")

    matches["match_id"] = matches["match_id"].astype(int)

    partecipant_names = (
        partecipants["partecipant"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    partecipant_names = sorted(set([x for x in partecipant_names if x != ""]))

    rows = []

    for partecipant in partecipant_names:
        for match_id in matches["match_id"].tolist():
            rows.append(
                {
                    "partecipant": partecipant,
                    "match_id": int(match_id),
                    "pred_home_score": "",
                    "pred_away_score": "",
                    "pred_result": "",
                    "pred_scorer": "",
                    "last_update": "",
                }
            )

    new_df = pd.DataFrame(rows)

    if PREDICTIONS_PATH.exists():
        old_df = read_csv(PREDICTIONS_PATH)

        # Migrazione automatica vecchia colonna participant -> partecipant
        if "participant" in old_df.columns and "partecipant" not in old_df.columns:
            old_df = old_df.rename(columns={"participant": "partecipant"})

        required_cols = {
            "partecipant",
            "match_id",
            "pred_home_score",
            "pred_away_score",
            "pred_result",
            "pred_scorer",
            "last_update",
        }

        if required_cols.issubset(old_df.columns):
            old_df["match_id"] = old_df["match_id"].astype(int)

            old_data = old_df[list(required_cols)].copy()

            merged = new_df.merge(
                old_data,
                on=["partecipant", "match_id"],
                how="left",
                suffixes=("", "_old"),
            )

            for col in [
                "pred_home_score",
                "pred_away_score",
                "pred_result",
                "pred_scorer",
                "last_update",
            ]:
                old_col = f"{col}_old"

                if old_col in merged.columns:
                    merged[col] = merged[old_col].combine_first(merged[col])
                    merged = merged.drop(columns=[old_col])

            new_df = merged[
                [
                    "partecipant",
                    "match_id",
                    "pred_home_score",
                    "pred_away_score",
                    "pred_result",
                    "pred_scorer",
                    "last_update",
                ]
            ]

    save_csv_and_push(
        new_df,
        PREDICTIONS_PATH,
        f"Initialize predictions - {commit_suffix()}",
    )

    return new_df


# ============================================================
# STARTUP
# ============================================================

ensure_data_dir()

if "synced_once" not in st.session_state:
    sync_core_files_from_github()
    st.session_state["synced_once"] = True


# ============================================================
# UI
# ============================================================

st.title("⚙️ INNIAREBACK - Backend Mondiali 2026")

with st.sidebar:
    st.title("Menu")

    if github_enabled():
        st.success("GitHub persistence attiva")
    else:
        st.warning("GitHub persistence non configurata")

    page = st.radio(
        "Sezione",
        [
            "📊 Dashboard",
            "📅 Calendario",
            "✏️ Pronostici",
            "⚽ Risultati reali",
            "🏆 Classifica",
            "🛠️ Amministrazione",
        ],
    )


# ============================================================
# DASHBOARD
# ============================================================

if page == "📊 Dashboard":
    st.header("📊 Dashboard")

    matches = read_csv(MATCHES_PATH)
    predictions = read_csv(PREDICTIONS_PATH)
    standings = read_csv(STANDINGS_PATH)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("Partite", 0 if matches.empty else len(matches))

    with c2:
        if matches.empty or "home_score" not in matches.columns or "away_score" not in matches.columns:
            finished = 0
        else:
            finished = (
                matches["home_score"].notna()
                & matches["away_score"].notna()
                & (matches["home_score"].astype(str).str.strip() != "")
                & (matches["away_score"].astype(str).str.strip() != "")
            ).sum()

        st.metric("Partite concluse", int(finished))

    with c3:
        if predictions.empty or "partecipant" not in predictions.columns:
            partecipants_count = 0
        else:
            partecipants_count = predictions["partecipant"].nunique()

        st.metric("Partecipanti", partecipants_count)

    with c4:
        if predictions.empty or "last_update" not in predictions.columns:
            updated = 0
        else:
            updated = (
                predictions["last_update"].notna()
                & (predictions["last_update"].astype(str).str.strip() != "")
            ).sum()

        st.metric("Pronostici compilati", int(updated))

    st.divider()

    if not standings.empty:
        st.subheader("Classifica attuale")
        st.dataframe(standings, width="stretch")
    else:
        st.info("Classifica non ancora calcolata.")


# ============================================================
# CALENDARIO
# ============================================================

elif page == "📅 Calendario":
    st.header("📅 Calendario")

    matches = read_csv(MATCHES_PATH)

    if matches.empty:
        st.warning("matches.csv non trovato o vuoto. Caricalo nella cartella data.")
    else:
        if "group" in matches.columns:
            groups = ["Tutti"] + sorted(matches["group"].dropna().astype(str).unique().tolist())
            selected_group = st.selectbox("Filtro gruppo", groups)
        else:
            selected_group = "Tutti"

        view = matches.copy()

        if selected_group != "Tutti" and "group" in view.columns:
            view = view[view["group"].astype(str) == selected_group]

        st.dataframe(view, width="stretch")


# ============================================================
# PRONOSTICI
# ============================================================

elif page == "✏️ Pronostici":
    st.header("✏️ Inserimento pronostici")

    predictions = read_csv(PREDICTIONS_PATH)
    matches = read_csv(MATCHES_PATH)

    if predictions.empty:
        st.warning("predictions.csv non trovato o vuoto.")

        if st.button("Inizializza predictions.csv"):
            try:
                df_init = init_predictions()
                st.success(f"predictions.csv creato/aggiornato: {len(df_init)} righe.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    elif matches.empty:
        st.warning("matches.csv non trovato o vuoto.")

    else:
        predictions["match_id"] = predictions["match_id"].astype(int)
        matches["match_id"] = matches["match_id"].astype(int)

        partecipants = sorted(predictions["partecipant"].dropna().astype(str).unique())

        selected_partecipant = st.selectbox(
            "Partecipante",
            partecipants,
        )

        df_user = predictions[
            predictions["partecipant"].astype(str) == selected_partecipant
        ].copy()

        match_info_cols = [
            "match_id",
            "datetime",
            "group",
            "home_team",
            "away_team",
        ]

        match_info_cols = [c for c in match_info_cols if c in matches.columns]

        view = df_user.merge(
            matches[match_info_cols],
            on="match_id",
            how="left",
        )

        editable_cols = [
            "match_id",
            "datetime",
            "group",
            "home_team",
            "away_team",
            "pred_home_score",
            "pred_away_score",
            "pred_result",
            "pred_scorer",
            "last_update",
        ]

        editable_cols = [c for c in editable_cols if c in view.columns]

        st.caption(
            "Compila pred_home_score, pred_away_score e pred_scorer. "
            "Il segno pred_result viene calcolato automaticamente."
        )

        edited = st.data_editor(
                 view[editable_cols],
                 width="stretch",
                 num_rows="fixed",
                 disabled=[
                 c for c in [
                 "match_id",
                 "datetime",
                 "group",
                 "home_team",
                 "away_team",
                 "pred_result",
                 "last_update",
                 ]
                 if c in editable_cols
                 ],
            column_config={
            "pred_scorer": st.column_config.TextColumn(
            "Marcatore",
            help="Inserisci il nome del marcatore oppure OG",
            ),
            "pred_home_score": st.column_config.NumberColumn(
            "Gol Casa",
            min_value=0,
            step=1,
            ),
            "pred_away_score": st.column_config.NumberColumn(
            "Gol Trasferta",
            min_value=0,
            step=1,
            ),
            },
            )

        if st.button("💾 Salva pronostici"):
            now = now_string()

            for _, row in edited.iterrows():
                match_id = int(row["match_id"])

                mask = (
                    (predictions["partecipant"].astype(str) == selected_partecipant)
                    & (predictions["match_id"].astype(int) == match_id)
                )

                pred_home = row.get("pred_home_score", "")
                pred_away = row.get("pred_away_score", "")
                pred_scorer = normalize_scorer(row.get("pred_scorer", ""))

                predictions.loc[mask, "pred_home_score"] = clean_value(pred_home)
                predictions.loc[mask, "pred_away_score"] = clean_value(pred_away)
                predictions.loc[mask, "pred_scorer"] = pred_scorer
                predictions.loc[mask, "pred_result"] = calc_result(pred_home, pred_away)

                if (
                    clean_value(pred_home) != ""
                    or clean_value(pred_away) != ""
                    or clean_value(pred_scorer) != ""
                ):
                    predictions.loc[mask, "last_update"] = now
                else:
                    predictions.loc[mask, "last_update"] = ""

            save_csv_and_push(
                predictions,
                PREDICTIONS_PATH,
                f"Update predictions - {commit_suffix()}",
            )

            st.success("Pronostici salvati su GitHub.")
            st.rerun()


# ============================================================
# RISULTATI REALI
# ============================================================

elif page == "⚽ Risultati reali":
    st.header("⚽ Inserimento risultati reali")

    matches = read_csv(MATCHES_PATH)

    if matches.empty:
        st.warning("matches.csv non trovato o vuoto.")
    else:
        edit_cols = [
            "match_id",
            "datetime",
            "group",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "real_scorers",
        ]

        edit_cols = [c for c in edit_cols if c in matches.columns]

        edited = st.data_editor(
            matches[edit_cols],
            width="stretch",
            num_rows="fixed",
            disabled=[
                c for c in [
                    "match_id",
                    "datetime",
                    "group",
                    "home_team",
                    "away_team",
                ]
                if c in edit_cols
            ],
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 Salva risultati reali"):
                for _, row in edited.iterrows():
                    match_id = int(row["match_id"])
                    mask = matches["match_id"].astype(int) == match_id

                    if "home_score" in matches.columns:
                        matches.loc[mask, "home_score"] = clean_value(row.get("home_score", ""))

                    if "away_score" in matches.columns:
                        matches.loc[mask, "away_score"] = clean_value(row.get("away_score", ""))

                    if "real_scorers" in matches.columns:
                        matches.loc[mask, "real_scorers"] = normalize_scorers_list(
                            row.get("real_scorers", "")
                        )

                save_csv_and_push(
                    matches,
                    MATCHES_PATH,
                    f"Update match results - {commit_suffix()}",
                )

                st.success("Risultati reali salvati su GitHub.")
                st.rerun()

        with col2:
            if st.button("🏆 Salva e calcola classifica"):
                for _, row in edited.iterrows():
                    match_id = int(row["match_id"])
                    mask = matches["match_id"].astype(int) == match_id

                    if "home_score" in matches.columns:
                        matches.loc[mask, "home_score"] = clean_value(row.get("home_score", ""))

                    if "away_score" in matches.columns:
                        matches.loc[mask, "away_score"] = clean_value(row.get("away_score", ""))

                    if "real_scorers" in matches.columns:
                        matches.loc[mask, "real_scorers"] = normalize_scorers_list(
                            row.get("real_scorers", "")
                        )

                save_csv_and_push(
                    matches,
                    MATCHES_PATH,
                    f"Update match results - {commit_suffix()}",
                )

                try:
                    player_points, standings = run_scoring()

                    if standings.empty:
                        st.warning("Nessuna partita con risultato reale completo.")
                    else:
                        st.success("Classifica calcolata e salvata su GitHub.")
                        st.dataframe(standings, width="stretch")
                except Exception as e:
                    st.error(str(e))


# ============================================================
# CLASSIFICA
# ============================================================

elif page == "🏆 Classifica":
    st.header("🏆 Classifica")

    if st.button("🔄 Ricalcola classifica"):
        try:
            player_points, standings = run_scoring()

            if standings.empty:
                st.warning("Nessuna partita con risultato reale completo.")
            else:
                st.success("Classifica ricalcolata e salvata su GitHub.")
                st.rerun()
        except Exception as e:
            st.error(str(e))

    standings = read_csv(STANDINGS_PATH)

    if standings.empty:
        st.info("Classifica non ancora disponibile.")
    else:
        st.subheader("Classifica generale")
        st.dataframe(standings, width="stretch")

    player_points = read_csv(PLAYER_POINTS_PATH)

    if not player_points.empty:
        st.subheader("Dettaglio punti partita per partita")

        partecipants = ["Tutti"] + sorted(player_points["partecipant"].dropna().astype(str).unique().tolist())
        selected = st.selectbox("Filtro partecipante", partecipants)

        view = player_points.copy()

        if selected != "Tutti":
            view = view[view["partecipant"].astype(str) == selected]

        st.dataframe(view, width="stretch")


# ============================================================
# AMMINISTRAZIONE
# ============================================================

elif page == "🛠️ Amministrazione":
    st.header("🛠️ Amministrazione")

    st.subheader("Stato persistenza")

    if github_enabled():
        token, repo, branch = get_github_config()
        st.success(f"GitHub configurato: {repo} / branch {branch}")
    else:
        st.error(
            "GitHub non configurato. Aggiungi GITHUB_TOKEN, GITHUB_REPO, "
            "GITHUB_BRANCH nei Secrets di Streamlit."
        )

    st.divider()

    st.subheader("Sync")

    if st.button("🔄 Sincronizza file core da GitHub"):
        try:
            sync_core_files_from_github()
            st.success("File core sincronizzati da GitHub.")
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
                    backup_path = BACKUP_DIR / selected_backup
                    restored = restore_backup(backup_path)
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


    st.subheader("Rigenerazione predictions")

    if st.button("🔄 Rigenera predictions da partecipants.csv"):
       try:
           df_init = init_predictions()
           st.success(f"predictions.csv rigenerato: {len(df_init)} righe.")
           st.rerun()
       except Exception as e:
           st.error(str(e))
