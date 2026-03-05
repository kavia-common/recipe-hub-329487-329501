import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables (no hardcoding).

    Expected env vars (provided by orchestrator via .env):
    - POSTGRES_URL
    - POSTGRES_USER
    - POSTGRES_PASSWORD
    - POSTGRES_DB
    - POSTGRES_PORT
    - BACKEND_CORS_ORIGINS (optional, comma-separated)
    """

    postgres_url: str
    cors_origins: list[str]


# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Load and validate settings from environment.

    Returns:
        Settings: parsed settings

    Raises:
        RuntimeError: if required environment variables are missing.
    """
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise RuntimeError(
            "Missing required env var POSTGRES_URL. "
            "It should look like: postgresql://localhost:5000/myapp"
        )

    cors_env = os.getenv("BACKEND_CORS_ORIGINS", "*").strip()
    cors_origins = ["*"] if cors_env == "*" else [o.strip() for o in cors_env.split(",") if o.strip()]

    return Settings(postgres_url=postgres_url, cors_origins=cors_origins)
