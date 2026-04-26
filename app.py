import json
import io
import os
import requests
import streamlit as st
from pathlib import Path
from openai import OpenAI

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

st.set_page_config(page_title="AI Document Orchestrator", layout="wide")

# --- Helpers ---

def get_secret(name: str):
    if hasattr(st, "secrets"):
        if name in st.secrets:
            return st.secrets[name]
    return os.environ.get(name)


def load_client():
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def extract_text(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    mime = (uploaded_file.type or "").lower()

    if "text" in mime or uploaded_file.name.lower().endswith(".txt"):
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")

    if "pdf" in mime or uploaded_file.name.lower().endswith(".pdf"):
        if pdfplumber is None:
            return "(pdfplumber not installed)"
        try:
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                return "\n".join([p.extract_text() or "" for p in pdf.pages])
        except Exception as e:
            return f"(PDF error: {e})"
    return ""


def build_schema():
    return {
        "summary": "",
        "risk_level": "",
        "currency": "",
        "amount": 0,
        "amount_in_usd": 0,
        "insights": []
    }


def demo_extraction(question: str):
    return {
        "summary": "(DEMO MODE)",
        "risk_level": "Low",
        "currency": "$",
        "amount": 100,
        "amount_in_usd": 100,
        "insights": [{"field": "demo", "value": "API key missing"}]
    }


# 
def call_openai(client, text: str, question: str):
    if not client:
        st.warning("Missing OPENAI_API_KEY")
        return demo_extraction(question)

    if not text.strip():
        st.error("No text extracted")
        return None

    prompt = """
You are an expert document analyst.

Return STRICT JSON with:
- summary (must include currency symbol)
- risk_level (High/Medium/Low)
- currency
- amount
- amount_in_usd
- insights (exactly 4 key fields)
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.4-mini-2026-03-17",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"{question}\n\n{text}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        st.error(f"OpenAI API Error: {str(e)}")
        return demo_extraction(question)


def send_to_n8n(n8n_url, text, extracted_json, question, recipient):
    if not n8n_url:
        return {"status": "Simulated"}

    payload = {
        "text": text,
        "extracted_json": extracted_json,
        "question": question,
        "recipient_email": recipient,
    }

    try:
        resp = requests.post(n8n_url, json=payload)
        return resp.json()
    except Exception as e:
        st.error(f"n8n error: {e}")
        return None


# --- UI ---

st.title("AI Document Orchestrator")

uploaded = st.file_uploader("Upload PDF or TXT", type=["pdf", "txt"])

question = st.text_input(
    "Ask a question",
    value="Extract invoice details"
)

if "data" not in st.session_state:
    st.session_state.data = None

if uploaded:
    text = extract_text(uploaded)
    client = load_client()

    if st.button("Analyze"):
        with st.spinner("Processing..."):
            st.session_state.data = call_openai(client, text, question)

if st.session_state.data:
    st.json(st.session_state.data)

    risk = st.session_state.data.get("risk_level", "Low")
    amount = st.session_state.data.get("amount_in_usd", 0)

    if risk == "High" or amount > 500:
        st.warning(" Action Required")

        email = st.text_input("Recipient email")

        if st.button("Send Alert"):
            resp = send_to_n8n(
                get_secret("N8N_WEBHOOK_URL"),
                text,
                st.session_state.data,
                question,
                email
            )
            st.success(f"Sent: {resp}")
    else:
        st.success("✅ No action needed")
