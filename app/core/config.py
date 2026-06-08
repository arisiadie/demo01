from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "OralCare Agentic RAG")
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    knowledge_path: Path = Path(os.getenv("KNOWLEDGE_PATH", "./data/knowledge/oral_health_knowledge.json"))
    chroma_path: Path = Path(os.getenv("CHROMA_PATH", "./data/chroma"))
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "oralcare_knowledge")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY") or None
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", os.getenv("LLM_MODEL_NAME", "deepseek-v4-pro"))
    deepseek_enabled: bool = os.getenv("DEEPSEEK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    deepseek_timeout_seconds: float = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))
    llm_input_price_per_1m: float = float(os.getenv("LLM_INPUT_PRICE_PER_1M", "0"))
    llm_output_price_per_1m: float = float(os.getenv("LLM_OUTPUT_PRICE_PER_1M", "0"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    notification_scan_interval_seconds: int = int(os.getenv("NOTIFICATION_SCAN_INTERVAL_SECONDS", "3600"))
    auth_secret_key: str = os.getenv("AUTH_SECRET_KEY", "oralcare-agentic-rag-dev-secret")
    auth_token_ttl_seconds: int = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "28800"))

    @property
    def resolved_knowledge_path(self) -> Path:
        return self.knowledge_path if self.knowledge_path.is_absolute() else BASE_DIR / self.knowledge_path

    @property
    def resolved_upload_dir(self) -> Path:
        return self.upload_dir if self.upload_dir.is_absolute() else BASE_DIR / self.upload_dir

    @property
    def resolved_chroma_path(self) -> Path:
        return self.chroma_path if self.chroma_path.is_absolute() else BASE_DIR / self.chroma_path

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw_path = self.database_url.removeprefix(prefix)
        path = Path(raw_path)
        return path if path.is_absolute() else BASE_DIR / path


settings = Settings()
