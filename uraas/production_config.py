"""
Production configuration module for Render deployment.
Detects production environment and applies security-hardened settings.
"""

import logging
import os
from typing import Any, Dict


class ProductionConfig:
    """Production configuration for Render deployment."""

    @staticmethod
    def is_production() -> bool:
        """Detect if running on Render."""
        return os.getenv("RENDER") == "true"

    @staticmethod
    def apply_config(app) -> None:
        """
        Apply production configuration to Flask app.
        Only applies settings when running on Render.
        """
        if not ProductionConfig.is_production():
            return

        # Disable debug mode in production (CRITICAL for security)
        app.config["DEBUG"] = False
        app.config["TESTING"] = False

        # Security settings for HTTPS
        app.config["SESSION_COOKIE_SECURE"] = True  # HTTPS only
        app.config["SESSION_COOKIE_HTTPONLY"] = True  # No JavaScript access
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # CSRF protection

        # Use production secret key from environment
        secret_key = os.getenv("DASHBOARD_SECRET_KEY")
        if secret_key:
            app.config["SECRET_KEY"] = secret_key
        else:
            # Fallback - generate random key if not provided
            import secrets

            app.config["SECRET_KEY"] = secrets.token_hex(32)
            logging.warning("DASHBOARD_SECRET_KEY not set, using generated key")

        # Database configuration
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            # Render provides postgres:// but SQLAlchemy needs postgresql://
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql://", 1)
            app.config["SQLALCHEMY_DATABASE_URI"] = database_url

        # SQLAlchemy engine options for production
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_size": 5,
            "pool_recycle": 3600,  # Recycle connections after 1 hour
            "pool_pre_ping": True,  # Verify connections before using
            "max_overflow": 10,
            "pool_timeout": 30,
        }

        # Storage configuration
        app.config["STORAGE_PATH"] = os.getenv(
            "STORAGE_PATH", "/opt/render/project/storage"
        )

        # Ensure storage directory exists
        storage_path = app.config["STORAGE_PATH"]
        pdf_path = os.path.join(storage_path, "pdfs")
        os.makedirs(pdf_path, exist_ok=True)

        # Configure production logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Suppress noisy loggers
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("socketio").setLevel(logging.WARNING)
        logging.getLogger("engineio").setLevel(logging.WARNING)

        app.logger.info("=" * 70)
        app.logger.info("Production configuration applied")
        app.logger.info(
            f"Database: {database_url[:50] if database_url else 'Not configured'}..."
        )
        app.logger.info(f"Storage: {storage_path}")
        app.logger.info(f"Secret key: {'✓ Set' if secret_key else '⚠ Generated'}")
        app.logger.info("=" * 70)

    @staticmethod
    def get_config_dict() -> Dict[str, Any]:
        """Return configuration as dictionary for inspection."""
        return {
            "is_production": ProductionConfig.is_production(),
            "database_url": os.getenv("DATABASE_URL", "Not set")[:50] + "...",
            "storage_path": os.getenv("STORAGE_PATH", "Not set"),
            "secret_key_set": bool(os.getenv("DASHBOARD_SECRET_KEY")),
            "render_env": os.getenv("RENDER", "Not set"),
        }
