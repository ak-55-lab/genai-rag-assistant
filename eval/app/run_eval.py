"""Main CLI entrypoint for running a RAGAS eval pass end to end:
collect answers+contexts from n8n, score with RAGAS, save a versioned
results file, print a summary.

Usage (inside the container):
    python -m app.run_eval --mode quick
    python -m app.run_eval --mode full
    python -m app.run_eval --mode quick --n 20 --seed 42   # reproducible sample
"""
import argparse
import json

from . import data_collector, ragas_scorer, config


def main():
    parser = argparse.ArgumentParser(description="Run a RAGAS eval pass against the n8n RAG agent")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick",
                         help="quick = random 15-20 question subset (fast, for iterating on changes); "
                              "full = all 161 golden questions (thorough baseline check)")
    parser.add_argument("--n", type=int, default=None, help="override subset size for quick mode")
    parser.add_argument("--seed", type=int, default=None, help="random seed, for a reproducible quick sample")
    args = parser.parse_args()

    def _progress(done, total, eval_id):
        print(f"  collecting [{done}/{total}] {eval_id}", flush=True)

    print(f"Running {args.mode} eval...")
    print(f"  chat webhook:          {config.N8N_CHAT_WEBHOOK_URL}")
    print(f"  eval-retrieve webhook: {config.N8N_EVAL_RETRIEVE_WEBHOOK_URL}")

    run_id, rows = data_collector.collect(mode=args.mode, n=args.n, seed=args.seed, progress_cb=_progress)
    print(f"\nCollected {len(rows)} rows (run_id={run_id}).")

    errors = [r for r in rows if r.get("collection_error")]
    if errors:
        print(f"WARNING: {len(errors)} question(s) failed to collect (webhook errors). They will be excluded from scoring:")
        for r in errors:
            print(f"  - {r['eval_id']}: {r['collection_error']}")

    print("\nScoring with RAGAS (this calls OpenAI as the judge)...")
    per_question, aggregates = ragas_scorer.score_rows(rows, run_id, args.mode)

    print("\n=== RESULTS ===")
    print(json.dumps(aggregates["overall"], indent=2))
    print(f"\nFlagged (below {aggregates['flag_threshold']} on at least one metric): {len(aggregates['flagged_questions'])}")
    for q in aggregates["flagged_questions"][:10]:
        print(f"  - {q}")
    print(f"\nFull results saved: results/runs/{run_id}_results.json")


if __name__ == "__main__":
    main()
