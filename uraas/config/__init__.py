"""
Configuration package for URAAS
"""

# Import config from the root config module
import os

from dotenv import load_dotenv

from .institutions import InstitutionConfig, InstitutionRegistry, get_registry

load_dotenv()


class Config:
    # Database — defaults to SQLite for local dev.
    # In any PostgreSQL deployment, DATABASE_URL must be explicitly set as an env var.
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///uraas.db")

    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Storage
    STORAGE_PATH = os.getenv("STORAGE_PATH", "./storage")
    STORAGE_MIN_FREE_GB = float(os.getenv("STORAGE_MIN_FREE_GB", "10.0"))

    # Crawler
    RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "2.0"))
    MAX_DEPTH = int(os.getenv("MAX_DEPTH", "10"))
    CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", "16"))

    # Dashboard
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
    DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "dev-secret-key")

    # Authentication — credentials are env-provided; passwords are stored as
    # Werkzeug hashes (generate with:
    #   python -c "from werkzeug.security import generate_password_hash as g; \
    #              print(g('your-password'))"
    # ). Two roles: admin (full control) and viewer (read + OA downloads only).
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
    VIEWER_USERNAME = os.getenv("VIEWER_USERNAME", "viewer")
    VIEWER_PASSWORD_HASH = os.getenv("VIEWER_PASSWORD_HASH", "")

    # Comma-separated list of allowed origins for the SocketIO handshake.
    DASHBOARD_CORS_ORIGINS = os.getenv(
        "DASHBOARD_CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
    )

    @staticmethod
    def is_production() -> bool:
        """Production when on Render OR explicitly flagged (e.g. a UNILAG DMZ host)."""
        return os.getenv("RENDER") == "true" or os.getenv("URAAS_ENV") == "production"

    def validate(self) -> None:
        """Fail fast on insecure production config. Called at app startup."""
        if self.is_production():
            if (
                not self.DASHBOARD_SECRET_KEY
                or self.DASHBOARD_SECRET_KEY == "dev-secret-key"
            ):
                raise RuntimeError(
                    "DASHBOARD_SECRET_KEY must be set to a strong unique value in "
                    "production (the 'dev-secret-key' default is not allowed)."
                )
            if not self.ADMIN_PASSWORD_HASH:
                raise RuntimeError(
                    "ADMIN_PASSWORD_HASH must be set in production "
                    "(generate with werkzeug.security.generate_password_hash)."
                )
            # Warn if CORS origins haven't been tightened for production.
            # SocketIO will restrict to localhost-only origins which breaks the
            # live dashboard for remote users connecting to the UNILAG server.
            if "localhost" in self.DASHBOARD_CORS_ORIGINS:
                import warnings
                warnings.warn(
                    "DASHBOARD_CORS_ORIGINS still contains 'localhost' in production. "
                    "Set DASHBOARD_CORS_ORIGINS to the actual UNILAG HTTPS domain "
                    "(e.g. https://repository.unilag.edu.ng) in the environment.",
                    RuntimeWarning,
                    stacklevel=2,
                )

    def cors_origins(self) -> list:
        return [o.strip() for o in self.DASHBOARD_CORS_ORIGINS.split(",") if o.strip()]

    # OpenAlex — free API key (openalex.org/settings/api); keyless access is
    # being retired, so set this in production.
    OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
    OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "cokiki@unilag.edu.ng")

    # ARK persistent identifiers (Archival Resource Key) — 99999 is the
    # official test NAAN until the Africa PID Alliance NAAN registration lands.
    ARK_NAAN = os.getenv("ARK_NAAN", "99999")
    # Shoulder must use the betanumeric alphabet (no vowels / no 'l').
    ARK_SHOULDER = os.getenv("ARK_SHOULDER", "z1")

    # ── Public dashboard URL (needed for approval email links) ────────────────
    # Set to the URL users reach the dashboard at (no trailing slash).
    DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8080").rstrip("/")

    # ── Live DSpace IR (api-ir.unilag.edu.ng) ────────────────────────────────
    # Backend API base — NOT the Angular frontend URL.
    DSPACE_API_URL = os.getenv("DSPACE_API_URL", "https://api-ir.unilag.edu.ng/server").rstrip("/")
    DSPACE_USERNAME = os.getenv("DSPACE_USERNAME", "")
    DSPACE_PASSWORD = os.getenv("DSPACE_PASSWORD", "")

    # ── SMTP for batch approval emails ────────────────────────────────────────
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "URAAS IR Deposit <uraas-bot@unilag.edu.ng>")
    S2_API_KEY = os.getenv("S2_API_KEY", "")
    CORE_API_KEY = os.getenv("CORE_API_KEY", "")
    NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
    LENS_API_KEY = os.getenv("LENS_API_KEY", "")


config = Config()

__all__ = ["InstitutionConfig", "InstitutionRegistry", "get_registry", "config"]
