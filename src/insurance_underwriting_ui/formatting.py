import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

FIELD_KINDS: dict[str, str] = {
    "mfa_enabled": "bool",
    "handles_personal_data": "bool",
    "handles_payment_card_data": "bool",
    "endpoint_detection_response": "bool",
    "offline_backups": "bool",
    "requested_limit_cad": "float",
    "requested_retention_cad": "float",
    "annual_revenue_cad": "float",
    "employee_count": "int",
    "prior_cyber_claims": "int",
}
REVIEW_ACTIONS = ("APPROVE", "MODIFY", "DECLINE", "REQUEST_INFORMATION")

_TRUE = frozenset({"oui", "yes", "true", "vrai", "1", "y", "o"})
_FALSE = frozenset({"non", "no", "false", "faux", "0", "n"})
_NUMBER_NOISE = re.compile(r"[\s,_$]")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any, decimals: int = 0) -> str:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", " ")


def _timestamp(value: Any) -> str:
    return str(value or "")[:19].replace("T", " ")


def email_rows(records: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        email = _dict(record.get("email"))
        decision = _dict(_dict(record.get("response")).get("decision"))
        rows.append(
            {
                "Sujet": str(email.get("subject") or ""),
                "Expéditeur": str(email.get("sender") or ""),
                "Statut": str(record.get("workflow_status", "")),
                "Décision": str(decision.get("decision") or "—"),
                "Traité le": _timestamp(record.get("processed_at")),
                "source_id": str(email.get("source_id", "")),
            }
        )
    return rows


def decision_summary(decision: Mapping[str, Any]) -> dict[str, str]:
    return {
        "decision": str(decision.get("decision") or "—"),
        "risk_score": _number(decision.get("risk_score")),
        "risk_band": str(decision.get("risk_band") or "—"),
        "premium": _number(decision.get("indicated_premium_cad")),
    }


def rule_rows(decision: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "Règle": f"{rule.get('rule_id', '')} — {rule.get('rule_name', '')}",
            "Résultat": "OK" if rule.get("passed") else "ÉCHEC",
            "Sévérité": str(rule.get("severity", "")),
            "Message": str(rule.get("message", "")),
        }
        for rule in map(_dict, _list(decision.get("rule_results")))
    ]


def condition_rows(decision: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "ID": str(c.get("condition_id", "")),
            "Catégorie": str(c.get("category", "")),
            "Condition": str(c.get("message", "")),
        }
        for c in map(_dict, _list(decision.get("conditions")))
    ]


def citation_rows(decision: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "title": str(c.get("source_document_title", "")),
            "section": str(c.get("section_reference", "")),
            "excerpt": str(c.get("excerpt", "")),
            "score": _number(c.get("relevance_score"), 2),
            "finding": str(c.get("supported_finding_id", "")),
        }
        for c in map(_dict, _list(decision.get("evidence")))
    ]


def factor_rows(factors: Any) -> list[dict[str, str]]:
    return [
        {str(key): str(value) for key, value in _dict(factor).items()}
        for factor in _list(factors)
    ]


def portfolio_metrics(decision: Mapping[str, Any]) -> dict[str, str]:
    context = _dict(decision.get("portfolio_context"))
    status = str(context.get("status", "UNAVAILABLE"))
    if status != "SUCCESS":
        return {"Statut": status, "Raison": str(context.get("failure_reason") or "—")}
    share = context.get("share_of_policies_with_claims")
    return {
        "Province": str(context.get("province", "—")),
        "Ratio sinistres/primes": _number(context.get("loss_ratio"), 3),
        "Fréquence des sinistres": _number(context.get("claim_frequency"), 3),
        "Sévérité moyenne (CAD)": _number(context.get("average_severity")),
        "Polices": _number(context.get("policy_count")),
        "Polices avec sinistre": _number(share, 3),
    }


def audit_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "Date": _timestamp(event.get("created_at")),
            "Événement": str(event.get("event_type", "")),
            "Détail": json.dumps(event.get("event_payload"), ensure_ascii=False),
        }
        for event in events
    ]


def completable_fields(record: Mapping[str, Any]) -> list[str]:
    missing = _list(_dict(record.get("response")).get("missing_fields"))
    return [str(field) for field in missing if str(field) in FIELD_KINDS]


def coerce_override(field: str, raw: str) -> bool | int | float | str:
    kind = FIELD_KINDS.get(field, "text")
    text = raw.strip()

    if kind == "bool":
        lowered = text.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"'{field}': répondre par oui ou non.")

    if kind in {"float", "int"}:
        try:
            number = float(_NUMBER_NOISE.sub("", text))
        except ValueError as error:
            raise ValueError(f"'{field}': nombre invalide.") from error
        if kind == "int":
            if not number.is_integer():
                raise ValueError(f"'{field}': un entier est attendu.")
            return int(number)
        return number

    return text


def build_overrides(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        field: coerce_override(field, raw)
        for field, raw in values.items()
        if raw.strip()
    }


def build_review_command(
    action: str,
    reviewer_id: str,
    comment: str,
    approved_limit_cad: float | None = None,
    annual_premium_cad: float | None = None,
    added_conditions_text: str = "",
) -> dict[str, Any]:
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"Action inconnue : {action}.")
    if not reviewer_id.strip():
        raise ValueError("L'identifiant du souscripteur est obligatoire.")
    if not comment.strip():
        raise ValueError("Un commentaire est obligatoire.")

    command: dict[str, Any] = {
        "action": action,
        "reviewer_id": reviewer_id.strip(),
        "comment": comment.strip(),
    }

    if action == "MODIFY":
        modifications: dict[str, Any] = {}
        if approved_limit_cad:
            modifications["approved_limit_cad"] = approved_limit_cad
        if annual_premium_cad:
            modifications["annual_premium_cad"] = annual_premium_cad
        added = [line.strip() for line in added_conditions_text.splitlines()]
        if any(added):
            modifications["added_conditions"] = [line for line in added if line]
        if not modifications:
            raise ValueError("Une modification doit changer au moins un terme.")
        command["modifications"] = modifications

    return command
