"""
Gunicorn configuration for production deployment on Render.
Optimized for Flask-SocketIO with WebSocket support.
"""

import multiprocessing
import os

# Server socket — default 8080 matches Dockerfile EXPOSE and health checks.
# HF Spaces overrides this with PORT=7860 via Space config.
port = os.getenv("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Worker processes
# Free tier: 2 workers, Starter tier: 4 workers
workers = int(os.getenv("GUNICORN_WORKERS", "2"))

# Worker class — must match Flask-SocketIO async_mode.
# app.py uses async_mode="threading", so we use gthread (synchronous + threads).
# Do NOT use eventlet or gevent here without also changing async_mode in SocketIO.
worker_class = "gthread"

# Threads per worker (for gthread worker_class)
threads = 4

# Worker connections
worker_connections = 1000

# Restart workers after handling this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Timeout for requests (120 seconds for long-running crawler operations)
timeout = 120

# Keep-alive connections
keepalive = 5

# Logging
accesslog = "-"  # Log to stdout (Render captures this)
errorlog = "-"  # Log to stderr (Render captures this)
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "uraas-dashboard"

# Graceful shutdown timeout
graceful_timeout = 30

# Preload app for faster worker spawning
preload_app = True

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (handled by Render's load balancer)
keyfile = None
certfile = None
