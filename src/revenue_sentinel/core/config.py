"""Configuration.

Every value comes from the environment (rule 12). `.env.example` is the committed
contract for which names exist; `tests/unit/test_config.py` asserts that this class
and that file agree, so the template cannot silently drift from the code.

Fields for capabilities that arrive in later sessions (model routing, budgets,
detector thresholds) are declared and validated here because `.env.example` already
documents them. A settings object that silently ignores half its own template is a
trap, not a simplification.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from revenue_sentinel.core.errors import ConfigurationError

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
"""Repository root -- `<root>/src/revenue_sentinel/core/config.py` walked up three levels."""

FIXTURES_DIR: Final[Path] = PROJECT_ROOT / "fixtures"

DemoMode = Literal["fixture", "live", "record"]
LogFormat = Literal["json", "console"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
AppEnv = Literal["local", "ci"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    """Application configuration, loaded from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # -- Application --------------------------------------------------------
    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # -- Database -----------------------------------------------------------
    # No default. A missing DATABASE_URL must stop the process, not fall back to
    # localhost:5432 -- which on this machine is a different database entirely.
    database_url: str

    # -- Demo mode (ADR-0007) ----------------------------------------------
    demo_mode: DemoMode = "fixture"
    anthropic_api_key: SecretStr | None = None

    # -- Model routing (Session 7) -----------------------------------------
    model_default: str = "claude-opus-5"
    model_utility: str = "claude-haiku-4-5"
    model_effort_default: Effort = "high"

    # -- Cost governance (Session 7) ---------------------------------------
    budget_run_usd: Decimal = Decimal("0.50")
    budget_incident_usd: Decimal = Decimal("2.00")
    budget_global_monthly_usd: Decimal = Decimal("25.00")

    limit_model_calls_per_run: int = Field(default=12, gt=0)
    limit_tool_calls_per_run: int = Field(default=30, gt=0)
    limit_node_executions_per_run: int = Field(default=40, gt=0)
    limit_run_wallclock_seconds: int = Field(default=300, gt=0)

    # -- Determinism --------------------------------------------------------
    seed: int = 20260801
    evaluation_timestamp: datetime = datetime.fromisoformat("2026-08-01T12:00:00+00:00")

    # -- Detector thresholds (Session 2) -----------------------------------
    detector_min_amount_usd: Decimal = Decimal("100000")
    detector_inactivity_days: int = Field(default=14, gt=0)
    detector_usage_growth_pct: int = Field(default=40, gt=0)

    # -- Governance (Session 5) --------------------------------------------
    approval_expiry_hours: int = Field(default=72, gt=0)
    policy_version: str = "v1"

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_no_key(cls, value: object) -> object:
        """Treat `ANTHROPIC_API_KEY=` as absent, not as a key that happens to be "".

        `.env.example` ships the name with an empty value, which is correct for the
        offline default. Without this, `DEMO_MODE=live` would pass the credential
        check at startup and fail at the first API call instead -- turning a clear
        configuration error into a confusing runtime one.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("evaluation_timestamp")
    @classmethod
    def _timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "EVALUATION_TIMESTAMP must be timezone-aware, e.g. 2026-08-01T12:00:00Z"
            )
        return value

    @field_validator("database_url")
    @classmethod
    def _url_must_be_psycopg(cls, value: str) -> str:
        # The driver is pinned in the URL because SQLAlchemy's bare `postgresql://`
        # resolves to psycopg2, which is not installed. The failure that produces is
        # opaque; this one is not.
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg:// driver")
        return value

    @model_validator(mode="after")
    def _live_mode_requires_a_key(self) -> Settings:
        if self.demo_mode in ("live", "record") and self.anthropic_api_key is None:
            raise ValueError(f"DEMO_MODE={self.demo_mode} requires ANTHROPIC_API_KEY to be set")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process.

    Cached because configuration is immutable for the life of the process. Tests
    that need a different configuration call `get_settings.cache_clear()`.
    """
    try:
        return Settings()
    except Exception as exc:  # re-raised immediately as our own type
        raise ConfigurationError(str(exc)) from exc
