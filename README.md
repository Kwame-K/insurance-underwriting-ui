# Insurance Underwriting UI

Streamlit console for the insurance agentic platform. It only calls existing
HTTP APIs (`insurance-email-intake`, `underwriting-agent`) and holds no
underwriting logic.

Pages: inbox and decision detail, email submission (paste or `.eml`),
human review queue.

    uv run streamlit run src/insurance_underwriting_ui/app.py
