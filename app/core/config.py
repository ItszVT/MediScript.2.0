"""Application settings, loaded from environment / .env (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MediScript"
    secret_key: str = "change-me-in-production"          # JWT signing
    access_token_expire_minutes: int = 60 * 24 * 7       # 7 days

    # Database. On Render, DATABASE_URL is provided by the managed Postgres.
    # Locally it defaults to a SQLite file so the app runs with zero setup.
    database_url: str = "sqlite:///./mediscript.db"

    # OCR: OCR.space Engine 3 is the ONLY engine.
    ocrspace_keys: str = "helloworld"                    # comma-separated
    ocr_timeout: int = 90

    # Matching thresholds
    match_threshold: int = 72
    manual_threshold: int = 60

    # Optional override of the medicine dataset CSV
    medicine_csv: str | None = None

    # Free public medicine-info APIs
    rxnorm_base: str = "https://rxnav.nlm.nih.gov/REST"
    openfda_base: str = "https://api.fda.gov"
    http_cache_ttl: int = 86_400                         # 1 day

    # Optional medical NER model (spaCy). Empty = use the built-in offline
    # heuristic detector. Set to a spaCy model name to enable, e.g.
    # "en_core_med7_lg" (Med7, label DRUG) or "en_ner_bc5cdr_md" (scispaCy,
    # label CHEMICAL). The model must be pip-installed; see README.
    drug_ner_model: str = ""
    drug_ner_labels: str = "DRUG,CHEMICAL"

    # CORS (same-origin app by default)
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def ocr_keys_list(self) -> list[str]:
        return [k.strip() for k in self.ocrspace_keys.split(",") if k.strip()]

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        # Render's Postgres URL uses the old "postgres://" scheme; SQLAlchemy
        # needs "postgresql://". Normalise it so deploys "just work".
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
