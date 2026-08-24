"""Collects RAG agent answers + retrieved contexts for a set of golden
questions, by calling the two n8n webhooks. No LLM judging happens here --
this module just gathers the raw data that ragas_scorer.py will score.
"""
import json
import random
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
import requests

from . import config

SHEET_NAME = "Golden Eval Set"

REQUIRED_COLUMNS = [
    "eval_id", "question", "ground_truth_answer", "reference_context",
    "source_document", "module_topic", "question_type", "difficulty", "keywords",
]


def load_golden_set(path=None):
    path = path or config.GOLDEN_SET_PATH
    df = pd.read_excel(path, sheet_name=SHEET_NAME)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"golden_set.xlsx is missing expected columns: {missing}")
    return df


def select_subset(df, mode="quick", n=None, seed=None):
    """mode='full' -> all rows. mode='quick' -> random sample of n (default
    random between QUICK_SUBSET_MIN and QUICK_SUBSET_MAX) rows, no fixed
    stratification -- pure random each time, per spec."""
    if mode == "full":
        return df.reset_index(drop=True)
    if mode != "quick":
        raise ValueError(f"Unknown mode: {mode}")

    rng = random.Random(seed)
    if n is None:
        n = rng.randint(config.QUICK_SUBSET_MIN, config.QUICK_SUBSET_MAX)
    n = min(n, len(df))
    sampled = df.sample(n=n, random_state=seed if seed is not None else rng.randint(0, 2**31))
    return sampled.reset_index(drop=True)


def _split_answer_and_metadata(raw_output):
    """The RAG Chat Agent returns one text blob containing the answer,
    a CITATIONS block, and a CONFIDENCE line. RAGAS should only see the
    actual answer text, not the citation/confidence footer, so split it
    out here. Falls back to the full text if the markers aren't found."""
    marker = "\n---\nCITATIONS:"
    if marker in raw_output:
        answer = raw_output.split(marker)[0].strip()
    else:
        answer = raw_output.strip()

    citations = None
    confidence = None
    if "CITATIONS:" in raw_output:
        citations = raw_output.split("CITATIONS:", 1)[1]
        if "CONFIDENCE:" in citations:
            citations = citations.split("CONFIDENCE:", 1)[0].strip()
    if "CONFIDENCE:" in raw_output:
        confidence = raw_output.split("CONFIDENCE:", 1)[1].strip().splitlines()[0].strip()

    return answer, citations, confidence


def _post_with_retry(url, payload, timeout, max_retries=5):
    """POST with retry-with-backoff specifically for 429s. Your n8n workflow
    reranks with a Cohere Trial key (10 calls/minute) on BOTH webhooks --
    the chat webhook reranks via 'Reranker Cohere', and eval-retrieve
    reranks separately via 'Reranker Cohere1'. That means every golden
    question burns 2 Cohere calls, so the real ceiling is ~5 questions/min.
    Firing requests back-to-back blows through that immediately. This
    retries on 429 with increasing backoff instead of just failing the row."""
    delay = 8
    for attempt in range(max_retries + 1):
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if attempt == max_retries:
            resp.raise_for_status()  # give up, raise the 429 as an error
        time.sleep(delay)
        delay = min(delay * 1.5, 30)
    return resp  # unreachable, keeps linters happy


def call_chat_webhook(question, session_id=None, timeout=None):
    session_id = session_id or f"eval-{uuid.uuid4()}"
    payload = {"action": "sendMessage", "chatInput": question, "sessionId": session_id}
    resp = _post_with_retry(
        config.N8N_CHAT_WEBHOOK_URL, payload, timeout or config.REQUEST_TIMEOUT_SECONDS,
    )
    data = resp.json()
    raw_output = data.get("output", "")
    answer, citations, confidence = _split_answer_and_metadata(raw_output)
    return {
        "raw_output": raw_output,
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
    }


def call_eval_retrieve_webhook(question, timeout=None):
    payload = {"question": question}
    resp = _post_with_retry(
        config.N8N_EVAL_RETRIEVE_WEBHOOK_URL, payload, timeout or config.REQUEST_TIMEOUT_SECONDS,
    )
    items = resp.json()
    contexts = []
    for item in items:
        doc = item.get("document", item) if isinstance(item, dict) else {}
        page_content = doc.get("pageContent") or doc.get("page_content") or ""
        if page_content:
            contexts.append(page_content)
    return contexts


def collect(mode="quick", n=None, seed=None, progress_cb=None):
    """Runs the full collection pass and returns a list of row dicts ready
    for RAGAS scoring, plus writes a raw snapshot to results/raw/.

    progress_cb(done, total, eval_id) is called after each question, if given
    -- used by the dashboard's background runner to report status.
    """
    df = load_golden_set()
    subset = select_subset(df, mode=mode, n=n, seed=seed)
    total = len(subset)

    rows = []
    for i, row in subset.iterrows():
        if i > 0 and config.INTER_QUESTION_DELAY_SECONDS > 0:
            time.sleep(config.INTER_QUESTION_DELAY_SECONDS)

        question = str(row["question"])
        try:
            chat_result = call_chat_webhook(question)
            contexts = call_eval_retrieve_webhook(question)
            error = None
        except Exception as e:
            chat_result = {"answer": "", "raw_output": "", "citations": None, "confidence": None}
            contexts = []
            error = str(e)

        rows.append({
            "eval_id": row["eval_id"],
            "question": question,
            "ground_truth_answer": row["ground_truth_answer"],
            "reference_context": row.get("reference_context"),
            "source_document": row.get("source_document"),
            "module_topic": row.get("module_topic"),
            "question_type": row.get("question_type"),
            "difficulty": row.get("difficulty"),
            "keywords": row.get("keywords"),
            "answer": chat_result["answer"],
            "raw_output": chat_result["raw_output"],
            "citations": chat_result["citations"],
            "confidence": chat_result["confidence"],
            "retrieved_contexts": contexts,
            "collection_error": error,
        })

        if progress_cb:
            progress_cb(i + 1, total, row["eval_id"])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}_{mode}_{total}q"
    raw_path = f"{config.RAW_DIR}/{run_id}.json"
    with open(raw_path, "w") as f:
        json.dump({
            "run_id": run_id,
            "mode": mode,
            "collected_at": timestamp,
            "question_count": total,
            "rows": rows,
        }, f, indent=2, default=str)

    return run_id, rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Collect RAG answers + contexts for golden set questions")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--n", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    def _print_progress(done, total, eval_id):
        print(f"[{done}/{total}] {eval_id}", flush=True)

    run_id, rows = collect(mode=args.mode, n=args.n, seed=args.seed, progress_cb=_print_progress)
    print(f"\nCollected {len(rows)} rows. run_id={run_id}")
