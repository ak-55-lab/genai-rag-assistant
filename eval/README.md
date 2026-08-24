# RAG Eval — RAGAS scoring for the GenAI Academy RAG agent

Scores the n8n RAG Chat Agent against a 161-question golden set using RAGAS's
standard four metrics: **Faithfulness, Answer Relevancy, Context Precision,
Context Recall**. Ships as a single Docker container with a password-gated
dashboard for browsing results and trends, plus a CLI for running evals.

## How it works

```
n8n (your own instance)
  ├─ /webhook/<id>/chat     → chat answers (published RAG Chat Agent)
  └─ /webhook/eval-retrieve → raw retrieved contexts (eval-only branch)
        ▲
        │ HTTP
        │
Docker container (this project)
  ├─ app/data_collector.py   → pulls answers + contexts per golden question
  ├─ app/ragas_scorer.py     → scores with RAGAS (needs OPENAI_API_KEY)
  ├─ results/runs/*.json     → one versioned file per eval run (trend history)
  └─ app/dashboard.py        → password-gated Flask UI on :8080
```

Your OpenAI API key never leaves your machine — you set it yourself as an
environment variable when you run the container.

## Prerequisites

1. Your own n8n instance with the RAG Chat Agent workflow (see
   `../n8n/workflow.json`) imported and published, including:
   - the Chat Trigger webhook (`Make Chat Publicly Available` = on)
   - the `eval-retrieve` webhook branch (Webhook → Qdrant Vector Store →
     Respond to Webhook)
2. Docker Desktop (or Docker Engine + Compose) installed and running.
3. An OpenAI API key with access to the judge model (`gpt-4o-mini` by
   default — cheap, ~$0.01-0.05 per quick run of 15-20 questions; a full
   161-question run costs more, roughly $0.10-0.40 depending on context
   sizes — check current OpenAI pricing since this is an estimate, not a
   quote).

## Setup

```bash
cp .env.example .env
# edit .env: set OPENAI_API_KEY and DASHBOARD_PASSWORD at minimum
```

## Run it

```bash
docker compose up --build
```

Dashboard: http://localhost:8080 — log in with `DASHBOARD_PASSWORD`.

From the dashboard you can trigger a **Quick eval** (random 15-20 questions,
~1-3 min, good for checking a change you just made) or a **Full eval** (all
161 questions, slower, use for periodic baseline checks).

## Run from the CLI instead

```bash
# quick random subset (15-20 questions, new random sample each time)
docker compose exec rag-eval python -m app.run_eval --mode quick

# reproducible subset (same 20 questions every time, useful for A/B comparing two prompt versions)
docker compose exec rag-eval python -m app.run_eval --mode quick --n 20 --seed 42

# full 161-question baseline
docker compose exec rag-eval python -m app.run_eval --mode full
```

Every run — from the CLI or the dashboard — writes a timestamped, versioned
results file to `results/runs/`, so trend tracking works no matter which
way you kick it off. Raw collected data (before scoring) is also saved to
`results/raw/` for debugging.

## Reading results

- **Overall metrics**: the four RAGAS scores averaged across the run, 0-100%.
- **Breakdowns**: same four metrics grouped by `module_topic`,
  `question_type`, and `difficulty` from the golden set — this is where
  you'll spot patterns (e.g. "Week 3 content" or "Analytical" questions
  scoring lower).
- **Flagged questions**: any question scoring below `FLAG_THRESHOLD`
  (default 70%) on at least one metric — start here when triaging what to
  improve.
- **Trend chart**: last 12 runs, one line per metric, so you can see whether
  changes to the prompt/retrieval config are helping or hurting over time.

## Recommended workflow

1. Run a **full baseline** once, before making changes.
2. After each change to the RAG Chat Agent (prompt, retrieval limit,
   reranker top-N, etc.), run a **quick eval** to get fast directional
   feedback.
3. Periodically re-run the **full eval** to catch regressions the random
   quick subset might miss.

## Deploying

Any Dockerfile-based platform works (Railway, Fly.io, Render, etc.) —
`PORT` env var support is already wired in. Your n8n instance needs to be
reachable from wherever this container runs; if n8n is only on your own
machine, either host it somewhere public too, or run this eval container
locally alongside it.

Required environment variables in production: `OPENAI_API_KEY`,
`DASHBOARD_PASSWORD`, `FLASK_SECRET_KEY`, `N8N_CHAT_WEBHOOK_URL`,
`N8N_EVAL_RETRIEVE_WEBHOOK_URL`.

## Troubleshooting

- **Connection refused to n8n from the container**: on Linux, confirm
  `extra_hosts` in `docker-compose.yml` is intact (adds
  `host.docker.internal` support — Docker Desktop has this built in). Quick
  check: `docker compose exec rag-eval curl -i http://host.docker.internal:5678`.
- **"OPENAI_API_KEY is not set"**: check `.env` has it, and that you ran
  `docker compose up` (not a stale container) after adding it.
- **Every question fails to collect**: verify the n8n workflow is published
  (not just saved) and both webhook URLs in `.env`/`config.py` match your
  actual n8n instance's webhook IDs.
- **RAGAS import errors**: rebuild the image (`docker compose up --build`)
  — dependency versions are pinned in `requirements.txt`.

## Project layout

```
app/
  config.py          # all env-var driven settings
  data_collector.py  # calls n8n webhooks, builds the raw eval dataset
  ragas_scorer.py     # RAGAS scoring + versioned results file
  run_eval.py        # CLI entrypoint (collect + score + summary)
  dashboard.py        # Flask app: login, results views, run trigger
  templates/          # dashboard HTML
data/
  golden_set.xlsx     # NOT included in this repo -- proprietary course
                       # content. Supply your own 161-row (or any size)
                       # golden set with the same columns (see
                       # ragas_scorer.py / data_collector.py for the
                       # expected schema).
results/
  raw/                # raw collected Q&A+context per run (debugging) -- gitignored
  runs/                # scored, versioned results (dashboard reads these) -- gitignored
```
