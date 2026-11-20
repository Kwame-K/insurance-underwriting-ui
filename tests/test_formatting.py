from typing import Any

import pytest

from insurance_underwriting_ui import formatting as fmt

DECISION: dict[str, Any] = {
    "decision_id": "DEC-1",
    "decision": "REFER",
    "risk_score": 44.0,
    "risk_band": "MEDIUM",
    "indicated_premium_cad": 18900.0,
    "rule_results": [
        {
            "rule_id": "UW-CYB-004",
            "rule_name": "Automated capacity authority",
            "passed": False,
            "severity": "REFERRAL",
            "message": "Limit too high.",
        },
        {
            "rule_id": "UW-CYB-001",
            "rule_name": "Territory",
            "passed": True,
            "severity": "DECLINE",
            "message": "ok",
        },
    ],
    "conditions": [
        {
            "condition_id": "COND-007",
            "category": "INFORMATION_REQUIRED",
            "message": "Provide exposure details.",
        }
    ],
    "evidence": [
        {
            "source_document_title": "Cyber Guide",
            "section_reference": "4.2",
            "excerpt": "Limits above authority are referred.",
            "relevance_score": 0.91,
            "supported_finding_id": "UW-CYB-004",
        }
    ],
    "portfolio_context": {
        "status": "SUCCESS",
        "province": "QC",
        "loss_ratio": 0.612,
        "claim_frequency": 0.08,
        "average_severity": 12500.0,
        "policy_count": 1234,
        "share_of_policies_with_claims": 0.07,
    },
}


def test_decision_summary_formats_numbers() -> None:
    summary = fmt.decision_summary(DECISION)

    assert summary == {
        "decision": "REFER",
        "risk_score": "44",
        "risk_band": "MEDIUM",
        "premium": "18 900",
    }


def test_decision_summary_handles_missing_values() -> None:
    summary = fmt.decision_summary({"decision": "NEED_MORE_INFORMATION"})

    assert summary["risk_score"] == "—"
    assert summary["premium"] == "—"


def test_rule_condition_and_citation_rows() -> None:
    rules = fmt.rule_rows(DECISION)
    assert [r["Résultat"] for r in rules] == ["ÉCHEC", "OK"]
    assert fmt.condition_rows(DECISION)[0]["ID"] == "COND-007"
    citation = fmt.citation_rows(DECISION)[0]
    assert citation["score"] == "0.91"
    assert citation["finding"] == "UW-CYB-004"


def test_portfolio_metrics_success_and_unavailable() -> None:
    assert fmt.portfolio_metrics(DECISION)["Province"] == "QC"
    unavailable = fmt.portfolio_metrics(
        {"portfolio_context": {"status": "UNAVAILABLE", "failure_reason": "refused"}}
    )
    assert unavailable == {"Statut": "UNAVAILABLE", "Raison": "refused"}


def test_email_rows_use_decision_when_present() -> None:
    record = {
        "email": {"source_id": "EML-1", "subject": "Cyber", "sender": "a@b.test"},
        "workflow_status": "EVALUATED",
        "processed_at": "2026-11-19T20:01:02.123+00:00",
        "response": {"decision": {"decision": "ACCEPT"}},
    }

    row = fmt.email_rows([record])[0]

    assert row["Décision"] == "ACCEPT"
    assert row["Traité le"] == "2026-11-19 20:01:02"
    assert row["source_id"] == "EML-1"


def test_completable_fields_keeps_only_overridable_ones() -> None:
    record = {
        "response": {
            "missing_fields": ["mfa_enabled", "postal_code", "requested_limit_cad"]
        }
    }

    assert fmt.completable_fields(record) == ["mfa_enabled", "requested_limit_cad"]


def test_coerce_override_handles_each_kind() -> None:
    assert fmt.coerce_override("mfa_enabled", " Oui ") is True
    assert fmt.coerce_override("mfa_enabled", "non") is False
    assert fmt.coerce_override("requested_limit_cad", "1,000,000") == 1_000_000.0
    assert fmt.coerce_override("employee_count", "35") == 35
    assert fmt.coerce_override("other", " text ") == "text"


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("mfa_enabled", "peut-être"),
        ("requested_limit_cad", "abc"),
        ("employee_count", "3.5"),
    ],
)
def test_coerce_override_rejects_invalid_values(field: str, raw: str) -> None:
    with pytest.raises(ValueError, match=field):
        fmt.coerce_override(field, raw)


def test_build_overrides_skips_blank_values() -> None:
    values = {
        "mfa_enabled": "oui",
        "requested_limit_cad": "  ",
        "requested_retention_cad": "25000",
    }

    assert fmt.build_overrides(values) == {
        "mfa_enabled": True,
        "requested_retention_cad": 25000.0,
    }


def test_review_command_without_modifications() -> None:
    command = fmt.build_review_command("APPROVE", " uw-1 ", " ok ")

    assert command == {"action": "APPROVE", "reviewer_id": "uw-1", "comment": "ok"}


def test_review_command_modify_requires_a_change() -> None:
    with pytest.raises(ValueError, match="modification"):
        fmt.build_review_command("MODIFY", "uw-1", "adjust")

    command = fmt.build_review_command(
        "MODIFY",
        "uw-1",
        "adjust",
        approved_limit_cad=750_000.0,
        added_conditions_text="MFA required\n\n EDR proof ",
    )
    assert command["modifications"] == {
        "approved_limit_cad": 750_000.0,
        "added_conditions": ["MFA required", "EDR proof"],
    }


def test_review_command_validates_inputs() -> None:
    with pytest.raises(ValueError, match="commentaire"):
        fmt.build_review_command("DECLINE", "uw-1", "  ")
    with pytest.raises(ValueError, match="souscripteur"):
        fmt.build_review_command("DECLINE", " ", "reason")
    with pytest.raises(ValueError, match="Action"):
        fmt.build_review_command("DELETE", "uw-1", "reason")
