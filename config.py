"""Application configuration — loaded from environment variables.

On Render (or any PaaS), environment variables are injected directly.
Locally, they come from a .env file via python-dotenv.
"""
import os
from pathlib import Path

# Load .env only when running locally (not on Render)
if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME"):
    # Render sets env vars directly — skip .env loading
    _is_render = True
else:
    from dotenv import load_dotenv
    load_dotenv()
    _is_render = False

# ── Secrets (set in Render Dashboard → Environment) ──────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# LLM provider: "google" (Gemini) or "openai"
# Set via LLM_PROVIDER env var.  Defaults to "google".
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "google").lower().strip()

# API keys — only the one matching LLM_PROVIDER is required
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

# Gemini model name (change if you want a different model)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ── App settings ──────────────────────────────────────────────────────────
CURRENCY_SYMBOL: str = "\u20b9"  # ₹

# ── Database ──────────────────────────────────────────────────────────────
# On Render free tier the filesystem is ephemeral — SQLite data resets on
# each deploy.  For persistent storage either:
#   • Attach a Render Persistent Disk (paid) and change DB_PATH, or
#   • Switch to a free external SQLite host, or
#   • Upgrade to a tiny PostgreSQL add-on and change DB_URL.
#
# Default: store DB in /data (Render persistent disk mount point) when
# available, otherwise fall back to the repo root.
_DATA_DIR = Path(os.getenv("RENDER_DATA_DIR", "/data"))
if _DATA_DIR.exists():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db_file = _DATA_DIR / "fintrackbot.db"
    DB_URL: str = f"sqlite:///{_db_file}"
else:
    DB_URL: str = "sqlite:///fintrackbot.db"

# ── Budget warning thresholds ─────────────────────────────────────────────
BUDGET_WARN_THRESHOLD: float = float(os.getenv("BUDGET_WARN_THRESHOLD", "0.80"))
BUDGET_ALERT_THRESHOLD: float = float(os.getenv("BUDGET_ALERT_THRESHOLD", "1.00"))