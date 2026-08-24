"""GenAI -- password-gated public chat front-end for the n8n RAG Chat Agent.

Single-file Flask app on purpose: this is a thin proxy + login gate, not the
eval/scoring project (that's the separate rag_eval_docker package). It holds
no OpenAI key and does no scoring -- it just forwards chat messages to your
n8n chat webhook and renders the reply.
"""
import os
import re
import uuid
from functools import wraps

import requests
from flask import Flask, request, session, redirect, url_for, render_template, jsonify

APP_NAME = "GenAI"

# Everyone shares this one password to get in the door. The "username" field
# on the login page is NOT checked against a fixed value -- it's just each
# person's own name, used to personalize their greeting ("Welcome, Akash").
#
# No real default on purpose -- set APP_PASSWORD and N8N_CHAT_WEBHOOK_URL as
# environment variables (see .env.example). This keeps live credentials and
# webhook URLs out of source control.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-" + os.urandom(8).hex())
N8N_CHAT_WEBHOOK_URL = os.environ.get("N8N_CHAT_WEBHOOK_URL", "")
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120"))

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        if not username:
            error = "Please enter your name."
        elif pw != APP_PASSWORD:
            error = "Incorrect password."
        else:
            session["authed"] = True
            session["username"] = username
            session["session_id"] = session.get("session_id") or f"genai-{uuid.uuid4()}"
            return redirect(request.args.get("next") or url_for("chat"))
    return render_template("login.html", app_name=APP_NAME, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def chat():
    return render_template("chat.html", app_name=APP_NAME, username=session.get("username", ""))


def _split_answer_and_metadata(raw_output):
    """The RAG Chat Agent returns one text blob with the answer, a CITATIONS
    block, and a CONFIDENCE line. Split them out for clean display."""
    if "CITATIONS:" in raw_output:
        answer = raw_output.split("CITATIONS:", 1)[0]
        answer = re.sub(r"-{3,}\s*$", "", answer).strip()
    else:
        answer = raw_output.strip()
        
    citations = None
    confidence = None
    if "CITATIONS:" in raw_output:
        citations = raw_output.split("CITATIONS:", 1)[1]
        if "CONFIDENCE:" in citations:
            citations = citations.split("CONFIDENCE:", 1)[0].strip()
        else:
            citations = citations.strip()
    if "CONFIDENCE:" in raw_output:
        confidence = raw_output.split("CONFIDENCE:", 1)[1].strip().splitlines()[0].strip()

    return answer, citations, confidence


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    if not N8N_CHAT_WEBHOOK_URL:
        return jsonify({"error": "N8N_CHAT_WEBHOOK_URL is not configured on the server."}), 500

    body = request.json or {}
    message = body.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    # Each sidebar conversation generates its own client-side session id so
    # separate chats get independent memory in n8n. Fall back to a
    # server-generated one if the client didn't send one (e.g. older client).
    client_session_id = (body.get("session_id") or "").strip()
    session_id = client_session_id or session.get("session_id") or f"genai-{uuid.uuid4()}"
    if not client_session_id:
        session["session_id"] = session_id

    try:
        resp = requests.post(
            N8N_CHAT_WEBHOOK_URL,
            json={"action": "sendMessage", "chatInput": message, "sessionId": session_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        raw_output = resp.json().get("output", "")
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach the RAG agent: {e}"}), 502

    answer, citations, confidence = _split_answer_and_metadata(raw_output)
    return jsonify({"answer": answer, "citations": citations, "confidence": confidence})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
