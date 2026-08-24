"""Central configuration, loaded from environment variables.

None of these are hardcoded. OPENAI_API_KEY in particular must be set by
whoever runs the container (docker run -e / --env-file / Railway dashboard).
This code never sees or logs the key value beyond passing it to the OpenAI
client libraries.
"""
import os

def _get(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it with -e {name}=... on `docker run`, in your .env file, "
            f"or in the Railway service's Variables tab."
        )
    return val

# --- n8n webhook endpoints -------------------------------------------------
# No real defaults shipped here on purpose -- point these at your own n8n
# instance. If n8n runs on your host machine and this app runs in Docker,
# host.docker.internal resolves to the host automatically on Docker Desktop
# (Mac/Windows); on Linux add --add-host=host.docker.internal:host-gateway
# (already included in docker-compose.yml).
N8N_CHAT_WEBHOOK_URL = _get(
    "N8N_CHAT_WEBHOOK_URL",
    "http://host.docker.internal:5678/webhook/your-webhook-id/chat",
)
N8N_EVAL_RETRIEVE_WEBHOOK_URL = _get(
    "N8N_EVAL_RETRIEVE_WEBHOOK_URL",
    "http://host.docker.internal:5678/webhook/eval-retrieve",
)

# --- RAGAS / OpenAI ----------------------------------------------------
# Never provided by Claude / baked into the image. Must be set by the user.
OPENAI_API_KEY = _get("OPENAI_API_KEY", required=False)  # required lazily, only when an eval actually runs
RAGAS_JUDGE_MODEL = _get("RAGAS_JUDGE_MODEL", "gpt-4o-mini")
RAGAS_EMBEDDING_MODEL = _get("RAGAS_EMBEDDING_MODEL", "text-embedding-3-small")

# --- Eval run defaults ---------------------------------------------------
QUICK_SUBSET_MIN = int(_get("QUICK_SUBSET_MIN", "15"))
QUICK_SUBSET_MAX = int(_get("QUICK_SUBSET_MAX", "20"))
REQUEST_TIMEOUT_SECONDS = int(_get("REQUEST_TIMEOUT_SECONDS", "120"))

# Pause between questions during collection. Your n8n workflow reranks with
# a Cohere Trial key (10 calls/min) on BOTH the chat webhook and the
# eval-retrieve webhook, so each question costs 2 Cohere calls -- an
# effective ceiling of ~5 questions/minute. 8s spacing keeps you under that
# even with retries. Set to 0 if you upgrade to a Cohere Production key.
INTER_QUESTION_DELAY_SECONDS = float(_get("INTER_QUESTION_DELAY_SECONDS", "8"))

# --- Dashboard -------------------------------------------------------------
DASHBOARD_PASSWORD = _get("DASHBOARD_PASSWORD", required=False)
FLASK_SECRET_KEY = _get("FLASK_SECRET_KEY", "change-me-" + os.urandom(8).hex())

# --- Paths -----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
GOLDEN_SET_PATH = _get("GOLDEN_SET_PATH", os.path.join(DATA_DIR, "golden_set.xlsx"))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
RAW_DIR = os.path.join(RESULTS_DIR, "raw")
RUNS_DIR = os.path.join(RESULTS_DIR, "runs")
STATUS_FILE = os.path.join(RESULTS_DIR, "current_run_status.json")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

# Score thresholds used to flag "needs improvement" in the dashboard (0-1 scale)
FLAG_THRESHOLD = float(_get("FLAG_THRESHOLD", "0.7"))
