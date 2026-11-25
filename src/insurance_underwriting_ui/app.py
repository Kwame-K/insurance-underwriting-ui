from typing import Any

import streamlit as st

from insurance_underwriting_ui import formatting as fmt
from insurance_underwriting_ui.agent_workspace import page_agents
from insurance_underwriting_ui.api import ApiError, IntakeClient, UnderwritingClient
from insurance_underwriting_ui.live import live_record_picker, render_health
from insurance_underwriting_ui.settings import get_settings

SAMPLE_BODY = (
    "Hello,\n\n"
    "NorthLake Analytics Inc. is a Montreal-based data consulting firm with\n"
    "approximately 35 employees and annual revenue of CAD 4,200,000.\n\n"
    "The company is seeking cyber liability coverage. Its office is located in\n"
    "Montreal, Quebec, postal code H3B 2Y5. No prior cyber incidents were "
    "reported\nin the submission.\n\nRegards,\nMarie"
)


@st.cache_resource
def get_clients() -> tuple[IntakeClient, UnderwritingClient]:
    settings = get_settings()
    return (
        IntakeClient(settings.intake_base_url, settings.request_timeout_seconds),
        UnderwritingClient(
            settings.underwriting_base_url, settings.request_timeout_seconds
        ),
    )


def flash(message: str) -> None:
    st.session_state["flash"] = message


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def render_decision(
    decision: dict[str, Any], persisted_id: str | None, uw: Any
) -> None:
    summary = fmt.decision_summary(decision)
    columns = st.columns(4)
    columns[0].metric("Décision", summary["decision"])
    columns[1].metric("Score de risque", summary["risk_score"])
    columns[2].metric("Bande de risque", summary["risk_band"])
    columns[3].metric("Prime indicative (CAD)", summary["premium"])

    for reason in decision.get("reasons") or []:
        st.markdown(f"- {reason}")
    for reason in decision.get("referral_reasons") or []:
        st.warning(f"Renvoi : {reason}")

    conditions = fmt.condition_rows(decision)
    if conditions:
        st.subheader("Conditions recommandées")
        st.dataframe(conditions, hide_index=True)

    citations = fmt.citation_rows(decision)
    status = decision.get("evidence_retrieval_status", "NOT_REQUESTED")
    st.subheader(f"Preuves documentaires (RAG) : {status}")
    if not citations:
        st.caption("Aucune citation : le RAG n'est sollicité que si une règle échoue.")
    for citation in citations:
        title = f"{citation['title']} — {citation['section']}"
        with st.expander(f"{title} (pertinence {citation['score']})"):
            st.write(citation["excerpt"])
            st.caption(f"Constat soutenu : {citation['finding']}")

    st.subheader("Contexte de portefeuille")
    st.dataframe([fmt.portfolio_metrics(decision)], hide_index=True)
    st.caption("Contexte seulement : il n'influence ni les règles ni le score.")

    with st.expander("Règles évaluées"):
        st.dataframe(fmt.rule_rows(decision), hide_index=True)
    with st.expander("Facteurs de risque et de pricing"):
        st.dataframe(fmt.factor_rows(decision.get("risk_factors")), hide_index=True)
        st.dataframe(fmt.factor_rows(decision.get("pricing_factors")), hide_index=True)

    if persisted_id:
        with st.expander("Audit trail"):
            st.dataframe(fmt.audit_rows(uw.audit_trail(persisted_id)), hide_index=True)


def render_result(result: dict[str, Any]) -> None:
    status = result.get("workflow_status") or result.get("status")
    st.info(f"Statut : {status} — décision : {result.get('decision') or '—'}")
    if result.get("missing_fields"):
        st.warning(f"Champs manquants : {', '.join(result['missing_fields'])}")
    if result.get("message"):
        st.caption(str(result["message"]))


def page_inbox(intake: IntakeClient, uw: UnderwritingClient) -> None:
    st.header("Boîte de réception")
    show_flash()
    if st.button("Analyser le dossier inbox maintenant"):
        results = intake.scan_inbox()
        st.toast(f"{len(results)} fichier(s) examiné(s).")

    live_record_picker(
        "inbox",
        intake.list_emails,
        lambda item: str(item["email"]["source_id"]),
        lambda item: (
            f"{item['email'].get('subject') or '(sans objet)'}"
            f" — {item['workflow_status']}"
        ),
        "Aucun courriel traité. Dépose un fichier .eml dans data/inbox.",
    )

    record = st.session_state.get("inbox_opened")
    if record is None:
        st.caption(
            "Choisis un courriel, puis clique sur « Ouvrir / recharger le dossier »."
        )
        return

    selected = str(record["email"]["source_id"])

    response = record.get("response") or {}
    email = record["email"]

    st.subheader(email.get("subject") or "(sans objet)")
    st.caption(f"De : {email.get('sender')} — langue : {email.get('language')}")
    if email.get("attachment_names"):
        st.warning(
            "Pièces jointes non traitées : " + ", ".join(email["attachment_names"])
        )
    st.text_area(
        "Contenu envoyé à l'extracteur", email["content"], height=180, disabled=True
    )

    workflow = record["workflow_status"]
    if workflow == "PENDING_INFORMATION":
        st.warning("Informations manquantes avant évaluation.")
        render_completion(intake, selected, record)
    elif workflow == "UNSUPPORTED_SUBMISSION":
        st.error("Hors périmètre : la soumission ne demande pas de couverture cyber.")

    decision = response.get("decision")
    if isinstance(decision, dict):
        persisted_id = (
            decision.get("decision_id") if response.get("persisted") else None
        )
        render_decision(decision, persisted_id, uw)


def render_completion(
    intake: IntakeClient, source_id: str, record: dict[str, Any]
) -> None:
    fields = fmt.completable_fields(record)
    if not fields:
        st.info(
            "Ces champs relèvent de l'extraction : le courtier doit renvoyer un "
            "courriel plus complet. Manquants : "
            + ", ".join(record["response"].get("missing_fields") or [])
        )
        return

    with st.form(f"complete-{source_id}"):
        st.write("Compléter le dossier (oui/non pour les contrôles, nombres en CAD).")
        values = {field: st.text_input(field) for field in fields}
        submitted = st.form_submit_button("Compléter et relancer l'analyse")

    if submitted:
        try:
            overrides = fmt.build_overrides(values)
        except ValueError as error:
            st.error(str(error))
            return
        if not overrides:
            st.warning("Renseigne au moins un champ.")
            return
        with st.spinner("Analyse en cours (10 à 20 s)..."):
            result = intake.complete(source_id, overrides)
            st.session_state.pop("inbox_opened", None)
        flash(
            f"Dossier relancé : {result.get('workflow_status')} / "
            f"{result.get('decision') or '—'}"
        )
        st.rerun()


def page_submit(intake: IntakeClient) -> None:
    st.header("Soumettre un courriel")
    paste_tab, eml_tab = st.tabs(["Coller un courriel", "Téléverser un .eml"])

    with paste_tab, st.form("paste-email"):
        sender = st.text_input("Expéditeur", "broker@example-brokerage.test")
        subject = st.text_input("Objet", "Cyber liability quote request")
        body = st.text_area("Corps du courriel", SAMPLE_BODY, height=260)
        pasted = st.form_submit_button("Envoyer aux agents")
    if pasted:
        with st.spinner("Extraction et underwriting en cours (10 à 20 s)..."):
            render_result(intake.submit_text(subject, body, sender))

    with eml_tab:
        uploaded = st.file_uploader("Fichier .eml", type=["eml"])
        if uploaded is not None and st.button("Envoyer le fichier"):
            with st.spinner("Extraction et underwriting en cours (10 à 20 s)..."):
                render_result(intake.submit_eml(uploaded.getvalue(), uploaded.name))

    st.caption("Le résultat apparaît ensuite dans la boîte de réception.")


def page_review(uw: UnderwritingClient) -> None:
    st.header("Revue humaine")
    show_flash()
    live_record_picker(
        "review",
        uw.list_pending_reviews,
        lambda item: str(item["decision_id"]),
        lambda item: f"{item['decision_id']} — {item['decision']}",
        "Aucune décision en attente de revue.",
    )

    decision = st.session_state.get("review_opened")
    if decision is None:
        st.caption("Choisis une décision, puis ouvre le dossier pour la revoir.")
        return

    selected = str(decision["decision_id"])

    render_decision(decision, selected, uw)

    st.subheader("Décision du souscripteur")
    action = st.selectbox("Action", fmt.REVIEW_ACTIONS)
    with st.form(f"review-{selected}"):
        reviewer = st.text_input("Identifiant du souscripteur", "underwriter-001")
        comment = st.text_area("Commentaire")
        limit = premium = None
        added = ""
        if action == "MODIFY":
            limit = st.number_input(
                "Limite approuvée (CAD, 0 = inchangée)", 0.0, step=50_000.0
            )
            premium = st.number_input(
                "Prime annuelle (CAD, 0 = inchangée)", 0.0, step=500.0
            )
            added = st.text_area("Conditions ajoutées (une par ligne)")
        submitted = st.form_submit_button("Enregistrer la décision")

    if submitted:
        try:
            command = fmt.build_review_command(
                action, reviewer, comment, limit, premium, added
            )
        except ValueError as error:
            st.error(str(error))
            return
        pending_ids = {str(item["decision_id"]) for item in uw.list_pending_reviews()}
        if selected not in pending_ids:
            st.warning(
                "Cette décision n’est plus en attente de revue. "
                "Actualise la liste avant de continuer."
            )
            return

        result = uw.review(selected, command)
        st.session_state.pop("review_opened", None)

        flash(f"Revue enregistrée : {result.get('review_status')}")
        st.rerun()


STYLES = """
<style>
footer {visibility: hidden;}
[data-testid="stMetric"] {
    background: rgba(128, 128, 128, 0.08);
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 10px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] p {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.7;
}
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title="Underwriting console",
        page_icon="",
        layout="wide",
    )
    st.markdown(STYLES, unsafe_allow_html=True)
    intake, uw = get_clients()

    pages = [
        st.Page(
            lambda: page_inbox(intake, uw),
            title="Boîte de réception",
            icon=":material/inbox:",
            url_path="inbox",
            default=True,
        ),
        st.Page(
            lambda: page_submit(intake),
            title="Soumettre un courriel",
            icon=":material/forward_to_inbox:",
            url_path="submit",
        ),
        st.Page(
            lambda: page_review(uw),
            title="Revue humaine",
            icon=":material/fact_check:",
            url_path="review",
        ),
        st.Page(
            page_agents,
            title="Interroger les agents",
            icon=":material/forum:",
            url_path="agents",
        ),
    ]

    current = st.navigation(pages, position="top")
    st.caption(
        "Insurance Agentic Platform · souscription cyber PME · données synthétiques"
    )
    with st.sidebar:
        render_health()

    try:
        current.run()
    except ApiError as error:
        st.error(f"Erreur du service : {error}")


main()
