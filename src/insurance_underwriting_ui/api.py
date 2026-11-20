from collections.abc import Mapping
from typing import Any

import httpx2


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _detail(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        for key in ("detail", "message"):
            if key in body:
                return str(body[key])
    return str(body)[:300]


def as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError("Unexpected response shape (object expected).")
    return value


def as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ApiError("Unexpected response shape (list expected).")
    return [as_dict(item) for item in value]


class JsonApi:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        try:
            with httpx2.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            ) as client:
                response = client.request(
                    method,
                    path,
                    json=json_body,
                    content=content,
                    headers=dict(headers) if headers else None,
                    params=dict(params) if params else None,
                )
        except httpx2.HTTPError as error:
            raise ApiError(f"Service unreachable: {error}") from error

        if response.status_code >= 400:
            raise ApiError(_detail(response), status_code=response.status_code)
        return response.json()

    def is_healthy(self) -> bool:
        try:
            self.request("GET", "/health")
        except ApiError:
            return False
        return True


class IntakeClient(JsonApi):
    def list_emails(self) -> list[dict[str, Any]]:
        return as_list(self.request("GET", "/v1/emails"))

    def submit_text(self, subject: str, body: str, sender: str) -> dict[str, Any]:
        return as_dict(
            self.request(
                "POST",
                "/v1/emails/text",
                json_body={"subject": subject, "body": body, "sender": sender},
            )
        )

    def submit_eml(self, raw: bytes, document_name: str) -> dict[str, Any]:
        return as_dict(
            self.request(
                "POST",
                "/v1/emails/eml",
                content=raw,
                headers={
                    "Content-Type": "message/rfc822",
                    "X-Document-Name": document_name,
                },
            )
        )

    def complete(self, source_id: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
        return as_dict(
            self.request(
                "POST",
                f"/v1/emails/{source_id}/complete",
                json_body={"overrides": dict(overrides)},
            )
        )

    def scan_inbox(self) -> list[dict[str, Any]]:
        return as_list(self.request("POST", "/v1/inbox/scan"))


class UnderwritingClient(JsonApi):
    def list_pending_reviews(self) -> list[dict[str, Any]]:
        return as_list(
            self.request("GET", "/decisions", params={"status": "PENDING_REVIEW"})
        )

    def audit_trail(self, decision_id: str) -> list[dict[str, Any]]:
        return as_list(self.request("GET", f"/decisions/{decision_id}/audit-trail"))

    def review(self, decision_id: str, command: Mapping[str, Any]) -> dict[str, Any]:
        return as_dict(
            self.request(
                "POST",
                f"/decisions/{decision_id}/review",
                json_body=dict(command),
            )
        )
