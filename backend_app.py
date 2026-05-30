# backend_app.py

from pathlib import Path
from datetime import datetime
import shutil

import pandas as pd
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
STANDINGS_PATH = DATA_DIR / "standings.csv"
PLAYER_POINTS_PATH = DATA_DIR / "player_points.csv"
TEAM_MAPPING_PATH = DATA_DIR / "team_mapping.csv"

POINTS_EXACT_SCORE = 5
POINTS_1X2 = 2
POINTS_SCORER = 3.5


st.set_page_config(
    page_title="INNIAREBACK Backend",
    page_icon="⚽",
    layout="wide",
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(
        path,
        sep=None,
        engine="python",
        encoding="utf-8-sig",
    )

    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    return df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


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
    elif home < away:
        return "2"
    else:
        return "X"


def normalize_scorer(value: str) -> str:
    value = clean_value(value)

    if value.upper() in ["OG", "AUTOGOL", "OWN GOAL"]:
        return "OG"

    return value


def normalize_scorers_list(value: str) -> str:
    value = clean_value(value)

    if value == "":
        return ""

    parts = [
        normalize_scorer(x)
        for x in value.split(";")
        if clean_value(x) != ""
    ]

    return ";".join(parts)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# SCORING HELPERS
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
        "participant",
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
        return pd.DataFrame(), pd.DataFrame()

    points = df.apply(score_row, axis=1)
    player_points = pd.concat([df, points], axis=1)

    keep_cols = [
        "participant",
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
        .groupby("participant", as_index=False)
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

    save_csv(player_points, PLAYER_POINTS_PATH)
    save_csv(standings, STANDINGS_PATH)

    return player_points, standings


# ============================================================
# BACKUP / RESET HELPERS
# ============================================================

def create_backup() -> Path:
    ensure_data_dir()

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}"
    backup_path.mkdir(parents=True, exist_ok=True)

    files_to_backup = [
        MATCHES_PATH,
        PREDICTIONS_PATH,
        PARTECIPANTS_PATH,
        TEAM_MAPPING_PATH,
        STANDINGS_PATH,
        PLAYER_POINTS_PATH,
    ]

    copied = 0

    for source in files_to_backup:
        if source.exists():
            shutil.copy2(source, backup_path / source.name)
            copied += 1

    return backup_path


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []

    return sorted(
        [
            p for p in BACKUP_DIR.iterdir()
            if p.is_dir() and p.name.startswith("backup_")
        ],
        reverse=True,
    )


def restore_backup(backup_path: Path) -> int:
    restored = 0

    for file_path in backup_path.glob("*.csv"):
        shutil.copy2(file_path, DATA_DIR / file_path.name)
        restored += 1

    return restored


def reset_tournament() -> None:
    matches = read_csv(MATCHES_PATH)

    if not matches.empty:
        for col in ["home_score", "away_score", "real_scorers"]:
            if col in matches.columns:
                matches[col] = ""
        save_csv(matches, MATCHES_PATH)

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
        save_csv(predictions, PREDICTIONS_PATH)

    for path in [STANDINGS_PATH, PLAYER_POINTS_PATH]:
        if path.exists():
            path.unlink()


# ============================================================
# INIT PREDICTIONS HELPER
# ============================================================

def init_predictions() -> pd.DataFrame:
    matches = read_csv(MATCHES_PATH)
    participants = read_csv(PARTECIPANTS_PATH)

    if matches.empty:
        raise ValueError("matches.csv non trovato o vuoto.")

    if participants.empty:
        raise ValueError("partecipants.csv non trovato o vuoto.")

    if "match_id" not in matches.columns:
        raise ValueError("matches.csv deve contenere la colonna match_id.")

    if "partecipant" in participants.columns:
        participant_col = "partecipant"
    elif "participant" in participants.columns:
        participant_col = "participant"
    else:
        raise ValueError(
            "partecipants.csv deve contenere la colonna partecipant "
            "oppure participant."
        )

    matches["match_id"] = matches["match_id"].astype(int)

    participant_names = (
        participants[participant_col]
        .dropna()
        .astype(str)
        .str.strip()
    )

    participant_names = [
        x for x in participant_names
        if x != ""
    ]

    participant_names = sorted(set(participant_names))

    rows = []

    for participant in participant_names:
        for match_id in matches["match_id"].tolist():
            rows.append(
                {
                    "participant": participant,
                    "match_id": match_id,
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

        required_cols = {
            "participant",
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
                on=["participant", "match_id"],
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
                    "participant",
                    "match_id",
                    "pred_home_score",
                    "pred_away_score",
                    "pred_result",
                    "pred_scorer",
                    "last_update",
                ]
            ]

    save_csv(new_df, PREDICTIONS_PATH)
    return new_df


# ============================================================
# UI
# ============================================================

ensure_data_dir()

st.title("⚙️ INNIAREBACK - Backend Mondiali 2026")

st.sidebar.title("Menu")

page = st.sidebar.radio(
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
        if matches.empty or "home_score" not in matches.columns:
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
        if predictions.empty or "participant" not in predictions.columns:
            participants_count = 0
        else:
            participants_count = predictions["participant"].nunique()
        st.metric("Partecipanti", participants_count)

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
        groups = ["Tutti"] + sorted(matches["group"].dropna().unique().tolist())

        selected_group = st.selectbox("Filtro gruppo", groups)

        view = matches.copy()

        if selected_group != "Tutti":
            view = view[view["group"] == selected_group]

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

        participants = sorted(predictions["partecipant"].dropna().unique())

        selected_participant = st.selectbox(
            "Partecipante",
            participants,
        )

        df_user = predictions[
            predictions["partecipant"] == selected_participant
        ].copy()

        match_info_cols = [
            "match_id",
            "datetime",
            "group",
            "home_team",
            "away_team",
        ]

        match_info_cols = [
            c for c in match_info_cols
            if c in matches.columns
        ]

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

        editable_cols = [
            c for c in editable_cols
            if c in view.columns
        ]

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
        )

        if st.button("💾 Salva pronostici"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for _, row in edited.iterrows():
                match_id = int(row["match_id"])

                mask = (
                    (predictions["partecipant"] == selected_participant)
                    & (predictions["match_id"] == match_id)
                )

                pred_home = row.get("pred_home_score", "")
                pred_away = row.get("pred_away_score", "")
                pred_scorer = normalize_scorer(row.get("pred_scorer", ""))

                predictions.loc[mask, "pred_home_score"] = clean_value(pred_home)
                predictions.loc[mask, "pred_away_score"] = clean_value(pred_away)
                predictions.loc[mask, "pred_scorer"] = pred_scorer
                predictions.loc[mask, "pred_result"] = calc_result(pred_home, pred_away)

                # Aggiorno last_update solo se almeno qualcosa è stato compilato
                if (
                    clean_value(pred_home) != ""
                    or clean_value(pred_away) != ""
                    or clean_value(pred_scorer) != ""
                ):
                    predictions.loc[mask, "last_update"] = now

            save_csv(predictions, PREDICTIONS_PATH)

            st.success("Pronostici salvati.")
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

        edit_cols = [
            c for c in edit_cols
            if c in matches.columns
        ]

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

                save_csv(matches, MATCHES_PATH)

                st.success("Risultati reali salvati.")
                st.rerun()

        with col2:
            if st.button("🏆 Salva e calcola classifica"):
                for _, row in edited.iterrows():
                    match_id = int(row["match_id"])
                    mask = matches["match_id"].astype(int) == match_id

                    matches.loc[mask, "home_score"] = clean_value(row.get("home_score", ""))
                    matches.loc[mask, "away_score"] = clean_value(row.get("away_score", ""))
                    matches.loc[mask, "real_scorers"] = normalize_scorers_list(
                        row.get("real_scorers", "")
                    )

                save_csv(matches, MATCHES_PATH)

                try:
                    player_points, standings = run_scoring()

                    if standings.empty:
                        st.warning("Nessuna partita con risultato reale completo.")
                    else:
                        st.success("Classifica calcolata.")
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
                st.success("Classifica ricalcolata.")
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

        participants = ["Tutti"] + sorted(player_points["participant"].dropna().unique().tolist())
        selected = st.selectbox("Filtro partecipante", participants)

        view = player_points.copy()

        if selected != "Tutti":
            view = view[view["participant"] == selected]

        st.dataframe(view, width="stretch")


# ============================================================
# AMMINISTRAZIONE
# ============================================================

elif page == "🛠️ Amministrazione":
    st.header("🛠️ Amministrazione")

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
            df = read_csv(path)
            st.write(f"**{path.name}** — {len(df)} righe")
