from pathlib import Path

import pandas as pd
import streamlit as st


def clean_auth_value(value) -> str:
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.lower() in ["nan", "none"]:
        return ""
    return value


def load_users(users_path: Path) -> pd.DataFrame:
    if not users_path.exists():
        return pd.DataFrame(columns=["username", "partecipant", "password", "role", "active"])
    try:
        users = pd.read_csv(users_path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=["username", "partecipant", "password", "role", "active"])
    users.columns = users.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
    for col in ["username", "partecipant", "password", "role", "active"]:
        if col not in users.columns:
            users[col] = ""
        users[col] = users[col].apply(clean_auth_value)
    return users


def is_active_user(value) -> bool:
    return clean_auth_value(value).lower() in ["true", "1", "yes", "y", "si", "sì"]


def login_box(users_path: Path) -> dict | None:
    users = load_users(users_path)

    if users.empty:
        st.error("File utenti non configurato: data/users.csv è assente o vuoto.")
        st.stop()

    if "auth_user" in st.session_state:
        return st.session_state["auth_user"]

    st.title("🔐 Login INNIAREBACK")
    st.caption("Inserisci username e password per accedere ai pronostici.")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Accedi")

    if submitted:
        username_clean = clean_auth_value(username)
        password_clean = clean_auth_value(password)
        matches = users[users["username"].astype(str).str.strip() == username_clean]

        if matches.empty:
            st.error("Utente non trovato.")
            st.stop()

        user = matches.iloc[0].to_dict()

        if not is_active_user(user.get("active", "")):
            st.error("Utente non attivo.")
            st.stop()

        if clean_auth_value(user.get("password", "")) != password_clean:
            st.error("Password errata.")
            st.stop()

        st.session_state["auth_user"] = user
        st.rerun()

    st.stop()


def logout_button() -> None:
    if st.sidebar.button("Logout"):
        st.session_state.pop("auth_user", None)
        st.rerun()


def user_is_admin(user: dict | None) -> bool:
    if not user:
        return False
    return clean_auth_value(user.get("role", "")).lower() == "admin"
