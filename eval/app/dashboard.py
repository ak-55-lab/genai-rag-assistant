"""Password-gated Flask dashboard for browsing RAGAS eval results and
kicking off new eval runs (quick or full) without touching a terminal.

Single shared password via DASHBOARD_PASSWORD env var -- simple by design,
per spec ("simple password for people to use and evaluate my project work").
"""
import glob
import json
import os
import threading
import traceback
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, session, redirect, url_for, render_template, jsonify

from . import config, data_collector, ragas_scorer

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

_run_lock = threading.Lock()
_run_state = {"status": "idle", "detail": "", "run_id": None, "started_at": None}


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
        pw = request.form.get("password", "")
        if config.DASHBOARD_PASSWORD and pw == config.DASHBOARD_PASSWORD:
            session["authed"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _list_runs():
    files = sorted(glob.glob(f"{config.RUNS_DIR}/*_results.json"), reverse=True)
    runs = []
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            runs.append(data["aggregates"])
        except Exception:
            continue
    return runs


@app.route("/")
@login_required
def dashboard():
    runs = _list_runs()
    latest = runs[0] if runs else None
    latest_detail = None
    if latest:
        path = f"{config.RUNS_DIR}/{latest['run_id']}_results.json"
        with open(path) as f:
            latest_detail = json.load(f)
    return render_template(
        "dashboard.html",
        latest=latest,
        latest_detail=latest_detail,
        runs=runs,
        run_state=_run_state,
        flag_threshold=config.FLAG_THRESHOLD,
    )


@app.route("/run/<run_id>")
@login_required
def run_detail(run_id):
    path = f"{config.RUNS_DIR}/{run_id}_results.json"
    if not os.path.exists(path):
        return "Run not found", 404
    with open(path) as f:
        data = json.load(f)
    return render_template("run_detail.html", run_id=run_id, data=data)


def _background_run(mode, n, seed):
    global _run_state
    with _run_lock:
        _run_state.update(status="collecting", detail="Starting...", run_id=None,
                           started_at=datetime.now(timezone.utc).isoformat())
    try:
        def _progress(done, total, eval_id):
            _run_state["detail"] = f"Collecting {done}/{total} ({eval_id})"

        run_id, rows = data_collector.collect(mode=mode, n=n, seed=seed, progress_cb=_progress)
        _run_state.update(status="scoring", detail="Scoring with RAGAS...", run_id=run_id)

        errors = [r for r in rows if r.get("collection_error")]
        if errors:
            _run_state["detail"] = f"Scoring ({len(errors)} question(s) failed to collect and will be skipped)..."

        per_question, aggregates = ragas_scorer.score_rows(rows, run_id, mode)
        _run_state.update(status="done", detail=f"Completed. {len(rows)} questions scored.", run_id=run_id)
    except Exception as e:
        traceback.print_exc()
        _run_state.update(status="error", detail=str(e))


@app.route("/api/run", methods=["POST"])
@login_required
def trigger_run():
    if _run_state["status"] in ("collecting", "scoring"):
        return jsonify({"error": "A run is already in progress"}), 409

    mode = request.json.get("mode", "quick") if request.is_json else request.form.get("mode", "quick")
    n = request.json.get("n") if request.is_json else request.form.get("n")
    n = int(n) if n else None

    if mode not in ("quick", "full"):
        return jsonify({"error": "mode must be 'quick' or 'full'"}), 400
    if not config.OPENAI_API_KEY:
        return jsonify({"error": "OPENAI_API_KEY is not set in this container's environment"}), 400

    t = threading.Thread(target=_background_run, args=(mode, n, None), daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": mode})


@app.route("/api/status")
@login_required
def status():
    return jsonify(_run_state)


@app.route("/api/runs")
@login_required
def api_runs():
    return jsonify(_list_runs())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
