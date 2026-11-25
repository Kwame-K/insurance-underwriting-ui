from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import httpx2 as httpx
import streamlit as st

from insurance_underwriting_ui.api import ApiError

Record = dict[str, Any]
Service = tuple[str, str]

SERVICE_CONFIG = (
    ("Email Intake", "INTAKE_BASE_URL", 8004),
    ("Submission Extractor", "SUBMISSION_EXTRACTOR_BASE_URL", 8000),
    ("Underwriting", "UNDERWRITING_BASE_URL", 8002),
    ("Data Analyst", "DATA_ANALYST_BASE_URL", 8003),
    ("Knowledge / RAG", "KNOWLEDGE_AGENT_BASE_URL", 8001),
)


def service_url(variable: str, port: int) -> str:
    return os.getenv(variable, f"http://127.0.0.1:{port}").strip().rstrip("/")


def _probe(service: Service) -> tuple[str, str, str]:
    label, base_url = service
    if not base_url:
        return label, "gray", "Non configuré"

    try:
        response = httpx.get(f"{base_url}/health", timeout=1.0)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return label, "red", "Indisponible"

    return label, "green", "OK"


@st.cache_data(ttl=8, show_spinner=False)
def _health_snapshot(
    services: tuple[Service, ...],
) -> tuple[list[tuple[str, str, str]], str]:
    with ThreadPoolExecutor(max_workers=len(services)) as executor:
        statuses = list(executor.map(_probe, services))
    return statuses, datetime.now().astimezone().strftime("%H:%M:%S")


@st.fragment(run_every="10s")
def render_health() -> None:
    st.subheader("Services")
    services = tuple(
        (label, service_url(variable, port)) for label, variable, port in SERVICE_CONFIG
    )
    statuses, checked_at = _health_snapshot(services)

    for label, color, status in statuses:
        st.markdown(f":{color}[●] {label} — {status}")


#  st.caption(
#     f"Contrôlé à {checked_at} · Healthy = API joignable, "
#    "pas une validation du portefeuille ni de l’index RAG."
# )


@st.fragment(run_every="15s")
def live_record_picker(
    namespace: str,
    fetch: Callable[[], list[Record]],
    record_id: Callable[[Record], str],
    record_label: Callable[[Record], str],
    empty_message: str,
) -> None:
    records_key = f"{namespace}_live_records"
    updated_key = f"{namespace}_live_updated"
    opened_key = f"{namespace}_opened"

    st.button("Actualiser la liste", key=f"{namespace}_refresh")

    try:
        st.session_state[records_key] = fetch()
        st.session_state[updated_key] = datetime.now().astimezone().strftime("%H:%M:%S")
    except ApiError:
        if records_key not in st.session_state:
            st.error("Impossible de charger la liste. Réessaie dans un instant.")
            return
        st.warning("Actualisation impossible : dernière liste connue affichée.")

    records: list[Record] = st.session_state[records_key]
    st.caption(
        f"{len(records)} dossier(s) · "
        f"dernière lecture à {st.session_state[updated_key]}"
    )

    by_id = {record_id(record): record for record in records}
    opened = st.session_state.get(opened_key)

    if opened is not None and record_id(opened) not in by_id:
        st.warning(
            "Le dossier ouvert ne figure plus dans la liste. "
            "Le détail n’a pas été remplacé automatiquement."
        )

    if not by_id:
        st.info(empty_message)
        return

    selected = st.selectbox(
        "Choisir un dossier",
        options=list(by_id),
        format_func=lambda value: record_label(by_id[value]),
        key=f"{namespace}_selection",
    )

    if st.button("Ouvrir / recharger le dossier", key=f"{namespace}_open"):  # noqa: SIM102
        if selected is not None:
            st.session_state[opened_key] = by_id[selected]
            st.rerun()
