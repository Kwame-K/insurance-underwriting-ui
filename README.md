# Insurance Underwriting UI

Streamlit console for the [Insurance Agentic Platform](https://github.com/Kwame-K/insurance-agentic-platform). It calls the existing Email Intake and Underwriting APIs. It does not implement extraction, underwriting rules, risk scoring, or pricing.

> This interface is intended for local demonstrations using synthetic submissions. It is not a production underwriting console.

## Pages

| Page | Purpose |
|---|---|
| Inbox and decision detail | Inspect stored email intake results and related underwriting decision details. |
| Email submission | Paste email text or submit an `.eml` file. |
| Human review queue | Access underwriting decisions awaiting review. |

The UI does not process PDF attachments. It sends email input to Email Intake, whose v1 contract processes text only.

## Architecture

```text
Browser → Streamlit UI
             ├──► Email Intake API       — email submission and stored intake results
             └──► Underwriting Agent API — decision details and human review
```

The [Email Intake API](https://github.com/Kwame-K/insurance-email-intake) forwards submission text to Underwriting. The [Underwriting Agent](https://github.com/Kwame-K/underwriting-agent) owns decision persistence and the review workflow. The UI does not replace either API.

## Run with Docker Compose

Clone this repository beside `insurance-agentic-platform` and the other application repositories. Follow the [platform setup and data initialization](https://github.com/Kwame-K/insurance-agentic-platform), then start the stack from the platform repository:

```bash
docker compose up --build -d
docker compose ps
```

Open `http://127.0.0.1:8501` in your browser.

In the platform, the service is named `underwriting-ui`. Compose passes `http://email-intake:8004` and `http://underwriting-agent:8002` to the UI as its API base URLs. The UI container waits for Email Intake to be healthy and for the Underwriting container to start. A successful UI health check does not prove that the backend workflow is ready.

## Run Locally

Start Email Intake and Underwriting, or leave those services running in the platform and use their published ports. Run the following from this repository with `uv`:

```bash
INTAKE_BASE_URL=http://127.0.0.1:8004 \
UNDERWRITING_BASE_URL=http://127.0.0.1:8002 \
REQUEST_TIMEOUT_SECONDS=120 \
uv run streamlit run src/insurance_underwriting_ui/app.py
```

Open the URL printed by Streamlit. If the Compose UI already uses port `8501`, stop that UI service first or run the local instance on another port:

```bash
INTAKE_BASE_URL=http://127.0.0.1:8004 \
UNDERWRITING_BASE_URL=http://127.0.0.1:8002 \
REQUEST_TIMEOUT_SECONDS=120 \
uv run streamlit run src/insurance_underwriting_ui/app.py --server.port 8502
```

## Configuration

| Environment variable | Local example | Platform value |
|---|---|---|
| `INTAKE_BASE_URL` | `http://127.0.0.1:8004` | `http://email-intake:8004` |
| `UNDERWRITING_BASE_URL` | `http://127.0.0.1:8002` | `http://underwriting-agent:8002` |
| `REQUEST_TIMEOUT_SECONDS` | `120` | Set from `UI_REQUEST_TIMEOUT_SECONDS`; defaults to `120` in Compose. |

Use host addresses when Streamlit runs on your machine and Compose service names when it runs in the platform container. These are URLs for the Streamlit process to reach, not URLs that the browser needs to resolve directly.

## Verify the Dependencies

From the host, with the platform running:

```bash
curl -f http://127.0.0.1:8004/health
curl -f http://127.0.0.1:8002/health
curl -f http://127.0.0.1:8501/_stcore/health
```

If Streamlit opens but cannot load records, check the two API base URLs and verify that both backend services are reachable. If an email appears in the inbox but no decision is available, check the intake result: a submission that still needs information may not have a persisted underwriting decision.
