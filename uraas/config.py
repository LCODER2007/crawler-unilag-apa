import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Database — defaults to local SQLite; Render overrides via DATABASE_URL.
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


config = Config()
