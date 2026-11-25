from __future__ import annotations

import math
from typing import Any
from uuid import uuid4

import httpx2 as httpx
import streamlit as st

from insurance_underwriting_ui.live import service_url


class AgentRequestError(Exception):
    pass


def _post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{base_url}{path}",
            json=(
                {key: value for key, value in payload.items() if key != "request_id"}
                if path == "/v1/ask"
                else payload
            ),
            headers={"X-Correlation-ID": str(payload["request_id"])},
            timeout=httpx.Timeout(
                60.0 if path == "/v1/ask" else 30.0,
                connect=2.0,
            ),
        )
    except httpx.TimeoutException as exc:
        raise AgentRequestError("Le service n’a pas répondu à temps.") from exc
    except httpx.HTTPError as exc:
        raise AgentRequestError("Impossible de joindre le service.") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise AgentRequestError(
            f"Réponse non JSON du service (HTTP {response.status_code})."
        ) from exc

    if not isinstance(body, dict):
        raise AgentRequestError("Le service a retourné un format inattendu.")

    if not response.is_success or body.get("status") == "error":
        error = body.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        detail = body.get("detail")
        if not message and isinstance(detail, str):
            message = detail
        raise AgentRequestError(
            str(message or f"Requête refusée (HTTP {response.status_code}).")
        )

    return body


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _render_chart(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    tool: str,
) -> None:
    # Vega-Lite : pas de dépendance de visualisation à ajouter au projet.
    dimensions = (
        ("year", "Année civile"),
        ("calendar_year", "Année civile"),
        ("underwriting_year", "Année de souscription"),
        ("province", "Province"),
        ("line_of_business", "Branche"),
    )
    labels = {
        "loss_ratio": "Ratio de sinistralité payé",
        "paid_loss_ratio": "Ratio de sinistralité payé",
        "claim_frequency": "Sinistres par unité d’exposition",
        "frequency": "Sinistres par unité d’exposition",
        "average_severity": "Sévérité moyenne (CAD)",
        "average_claim_severity": "Sévérité moyenne (CAD)",
        "claim_severity": "Sévérité moyenne (CAD)",
    }
    fallback_metrics = {
        "get_claim_frequency_trend": ("claim_frequency", "frequency"),
        "get_loss_ratio_by_segment": ("loss_ratio", "paid_loss_ratio"),
        "get_claim_severity": (
            "average_severity",
            "average_claim_severity",
            "claim_severity",
        ),
    }

    if metadata.get("chart_type") == "table":
        return

    y = metadata.get("y") or next(
        (
            name
            for name in fallback_metrics.get(tool, ())
            if any(_numeric(row.get(name)) is not None for row in rows)
        ),
        None,
    )
    x = metadata.get("x") or next(
        (
            name
            for name, _ in dimensions
            if any(row.get(name) is not None for row in rows)
        ),
        None,
    )
    if not x or not y:
        return

    series_fields = metadata.get("series")
    if not isinstance(series_fields, list):
        series_fields = [name for name, _ in dimensions if name != x]

    points = []
    for row in rows:
        value = _numeric(row.get(y))
        if value is None or row.get(x) is None:
            continue
        series = " · ".join(
            str(row[name])
            for name in series_fields
            if name != x and row.get(name) is not None
        )
        points.append(
            {"segment": str(row[x]), "valeur": value, "serie": series or "Portefeuille"}
        )

    if not points:
        return

    is_line = metadata.get("chart_type") == "line" or (
        tool == "get_claim_frequency_trend" and x in {"year", "calendar_year"}
    )
    # Si des points ne sont pas uniques, ne pas les agréger silencieusement.
    keys = {(point["segment"], point["serie"]) for point in points}
    if len(keys) != len(points):
        st.caption(
            "Graphique masqué : plusieurs valeurs existent pour un même segment."
        )
        return

    axis_format = ".1%" if y in {"loss_ratio", "paid_loss_ratio"} else ",.2f"
    x_title = dict(dimensions).get(x, str(x))
    y_title = labels.get(y, str(y).replace("_", " "))
    encoding: dict[str, Any] = {
        "x": {
            "field": "segment",
            "type": "ordinal",
            "sort": "ascending",
            "title": x_title,
        },
        "y": {
            "field": "valeur",
            "type": "quantitative",
            "title": y_title,
            "axis": {"format": axis_format},
        },
        "color": {"field": "serie", "type": "nominal", "title": "Série"},
        "tooltip": [
            {"field": "segment", "title": x_title},
            {"field": "serie", "title": "Série"},
            {
                "field": "valeur",
                "type": "quantitative",
                "title": y_title,
                "format": axis_format,
            },
        ],
    }
    if not is_line:
        encoding["xOffset"] = {"field": "serie"}

    spec = {
        "data": {"values": points},
        "height": 300,
        "mark": {"type": "line", "point": True} if is_line else {"type": "bar"},
        "encoding": encoding,
    }
    st.vega_lite_chart(spec=spec, use_container_width=True)


def _render_analyst(body: dict[str, Any]) -> None:
    data = body.get("data")
    if not isinstance(data, dict):
        st.error("Le résultat analytique est absent.")
        return

    if data.get("answer"):
        st.text(str(data["answer"]))

    raw_rows = data.get("raw_results") or []
    rows = [row for row in raw_rows if isinstance(row, dict)]

    if rows:
        tool_calls = data.get("tool_calls") or []
        first_call = tool_calls[0] if tool_calls else {}
        tool = str(first_call.get("tool_name", ""))
        _render_chart(rows, data.get("chart") or {}, tool)
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("Aucune ligne pour les filtres demandés.")

    audit = data.get("audit") or {}
    if audit.get("calculation_definition"):
        st.caption(f"Calcul : {audit['calculation_definition']}")
    if audit.get("dataset_version"):
        st.caption(f"Jeu de données : {audit['dataset_version']}")


def _render_rag(body: dict[str, Any]) -> None:
    status = body.get("retrieval_status")
    if status == "INSUFFICIENT_CONTEXT":
        st.warning("Aucun passage ne fournit de preuve suffisante pour cette question.")
    elif status == "PARTIAL":
        st.info("Résultat partiel : seules les preuves disponibles sont affichées.")

    for citation in body.get("citations") or []:
        title = citation["source_document_title"]
        section = citation.get("section_reference")
        with st.expander(f"{title} — {section}" if section else title):
            st.text(citation["excerpt"])
            st.caption(f"Document : {citation['source_document_id']}")

    if body.get("knowledge_base_version"):
        st.caption(f"Version du corpus : {body['knowledge_base_version']}")


def _render_rag_answer(body: dict[str, Any]) -> None:
    if body.get("grounded") is not True:
        st.warning("L’agent ne dispose pas de preuves suffisantes pour répondre.")
        if reason := body.get("insufficient_context_reason"):
            st.text(str(reason))
        return

    st.text(str(body["answer"]))

    citations = body.get("citations") or []
    if citations:
        st.caption("Citations vérifiées contre les passages récupérés")
        for citation in citations:
            title = citation["document_name"]
            section = citation.get("section_title")
            label = f"{title} — {section}" if section else title

            with st.expander(label):
                st.text(citation["quote"])
                st.caption(f"Passage : {citation['chunk_id']}")


def _agent_tab(agent: str) -> None:
    is_analyst = agent == "analyst"
    mode = "analyst"

    if is_analyst:
        url = service_url("DATA_ANALYST_BASE_URL", 8003)
        path = "/v1/analyze"
        example = "Afficher la fréquence des sinistres par province en 2024 et 2025."
    else:
        url = service_url("KNOWLEDGE_AGENT_BASE_URL", 8001)
        example = "Quelles sont les exigences de MFA pour la souscription cyber ?"

        selected_mode = st.radio(
            "Mode RAG",
            ["Réponse citée", "Passages sources"],
            horizontal=True,
            key="rag_mode",
        )
        mode = "ask" if selected_mode == "Réponse citée" else "evidence"
        path = "/v1/ask" if mode == "ask" else "/v1/retrieve-evidence"

        if mode == "ask":
            st.caption("Synthèse générée à partir de passages du corpus.")
        else:
            st.caption("Extraits documentaires, sans appel au modèle de génération.")

    if not url:
        st.info("Ce service n’est pas configuré.")
        return

    history_key = f"{agent}_history"
    history: list[dict[str, Any]] = st.session_state.setdefault(history_key, [])

    st.caption(f"Exemple : {example}")
    with st.form(f"{agent}_question_form", clear_on_submit=True):
        question = st.text_input("Ta question", max_chars=500)
        top_k = 3 if is_analyst else st.slider("Nombre maximal de passages", 1, 10, 3)
        submitted = st.form_submit_button("Poser la question")

    if submitted:
        question = question.strip()
        if len(question) < 3:
            st.warning("Saisis une question d’au moins trois caractères.")
        else:
            request_id = f"ui-{uuid4().hex}"
            if is_analyst:
                payload: dict[str, Any] = {
                    "question": question,
                    "request_id": request_id,
                    "include_chart": False,
                }
            elif mode == "ask":
                payload = {
                    "question": question,
                    "top_k": top_k,
                    "request_id": request_id,
                }

            else:
                payload = {
                    "request_id": request_id,
                    "top_k": top_k,
                    "queries": [
                        {"supported_finding_id": request_id, "query": question}
                    ],
                }

            try:
                with st.spinner("Interrogation de l’agent…"):
                    body = _post(url, path, payload)
                history.append({"question": question, "body": body, "mode": mode})
            except AgentRequestError as exc:
                history.append({"question": question, "error": str(exc)})

            del history[:-10]

    for entry in reversed(history):
        with st.container(border=True):
            st.text(entry["question"])
            if "error" in entry:
                st.error(entry["error"])
            elif is_analyst:
                _render_analyst(entry["body"])
            elif entry.get("mode") == "ask":
                _render_rag_answer(entry["body"])
            else:
                _render_rag(entry["body"])


def page_agents() -> None:
    st.header("Interroger les agents")
    st.caption(
        "Les métriques et les preuves documentaires n’affectent "
        "ni les décisions ni les primes."
    )
    analyst_tab, rag_tab = st.tabs(["Data Analyst", "RAG documentaire"])
    with analyst_tab:
        _agent_tab("analyst")
    with rag_tab:
        _agent_tab("rag")
