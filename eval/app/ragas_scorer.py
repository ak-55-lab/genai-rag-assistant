"""Scores collected rows with RAGAS's Standard 4 metrics:
Faithfulness, Answer Relevancy, Context Precision, Context Recall.

Requires OPENAI_API_KEY to be set in the container environment -- this
module reads it via config.py, which reads it from os.environ. The key is
never logged, written to disk, or included in results output.
"""
import json
import os
from datetime import datetime, timezone

import pandas as pd

from . import config


def _require_key():
    if not config.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set in this container's environment. "
            "RAGAS needs it as the LLM judge. Set it with `docker run -e OPENAI_API_KEY=...` "
            "or in your .env file / Railway variables, then retry."
        )
    # ragas/langchain read this from the environment directly
    os.environ.setdefault("OPENAI_API_KEY", config.OPENAI_API_KEY)


def score_rows(rows, run_id, mode):
    """rows: list of dicts from data_collector.collect().
    Returns (per_question_df, aggregates_dict) and writes a versioned
    results file to results/runs/{run_id}_results.json
    """
    _require_key()

    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    scorable_rows = [r for r in rows if not r.get("collection_error") and r.get("retrieved_contexts")]
    skipped = [r for r in rows if r not in scorable_rows]

    if not scorable_rows:
        raise RuntimeError("No rows had usable answers/contexts to score -- check n8n webhook connectivity.")

    samples = [
        {
            "user_input": r["question"],
            "response": r["answer"],
            "retrieved_contexts": r["retrieved_contexts"],
            "reference": r["ground_truth_answer"],
        }
        for r in scorable_rows
    ]
    dataset = EvaluationDataset.from_list(samples)

    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model=config.RAGAS_JUDGE_MODEL, temperature=0))
    evaluator_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=config.RAGAS_EMBEDDING_MODEL))

    metrics = [Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()]

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )
    scores_df = result.to_pandas()

    # Stitch the golden-set metadata (module_topic, question_type, difficulty)
    # back onto the scored rows for breakdown reporting.
    meta_cols = ["eval_id", "module_topic", "question_type", "difficulty", "source_document"]
    meta_df = pd.DataFrame(scorable_rows)[meta_cols]
    per_question = pd.concat([meta_df.reset_index(drop=True), scores_df.reset_index(drop=True)], axis=1)

    metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    metric_cols = [c for c in metric_cols if c in per_question.columns]

    overall = {c: round(float(per_question[c].mean()), 4) for c in metric_cols}

    def _breakdown(group_col):
        out = {}
        for key, g in per_question.groupby(group_col):
            out[str(key)] = {c: round(float(g[c].mean()), 4) for c in metric_cols}
        return out

    flagged = per_question[
        (per_question[metric_cols] < config.FLAG_THRESHOLD).any(axis=1)
    ][["eval_id"] + metric_cols].to_dict(orient="records")

    aggregates = {
        "run_id": run_id,
        "mode": mode,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "question_count": len(rows),
        "scored_count": len(scorable_rows),
        "skipped_count": len(skipped),
        "judge_model": config.RAGAS_JUDGE_MODEL,
        "overall": overall,
        "by_module_topic": _breakdown("module_topic"),
        "by_question_type": _breakdown("question_type"),
        "by_difficulty": _breakdown("difficulty"),
        "flag_threshold": config.FLAG_THRESHOLD,
        "flagged_questions": flagged,
    }

    results_path = f"{config.RUNS_DIR}/{run_id}_results.json"
    with open(results_path, "w") as f:
        json.dump({
            "aggregates": aggregates,
            "per_question": per_question.to_dict(orient="records"),
        }, f, indent=2, default=str)

    return per_question, aggregates


if __name__ == "__main__":
    import argparse
    from . import data_collector

    parser = argparse.ArgumentParser(description="Collect + score a RAGAS eval run")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--n", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    run_id, rows = data_collector.collect(mode=args.mode, n=args.n, seed=args.seed)
    print(f"Collected {len(rows)} rows (run_id={run_id}). Scoring with RAGAS...")
    per_question, aggregates = score_rows(rows, run_id, args.mode)
    print(json.dumps(aggregates, indent=2, default=str))
