import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from uraas.dashboard.app import app


def handler(event, context):
    """Netlify serverless function handler"""
    from io import BytesIO

    from werkzeug.wrappers import Request, Response

    # Convert Netlify event to WSGI environ
    environ = {
        "REQUEST_METHOD": event["httpMethod"],
        "SCRIPT_NAME": "",
        "PATH_INFO": event["path"],
        "QUERY_STRING": event.get("rawQuery", ""),
        "CONTENT_TYPE": event["headers"].get("content-type", ""),
        "CONTENT_LENGTH": str(len(event.get("body", ""))),
        "SERVER_NAME": event["headers"].get("host", "localhost"),
        "SERVER_PORT": "443",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": BytesIO(event.get("body", "").encode()),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
    }

    # Add headers
    for key, value in event.get("headers", {}).items():
        key = key.upper().replace("-", "_")
        if key not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            environ[f"HTTP_{key}"] = value

    # Call Flask app
    response = Response.from_app(app, environ)

    return {
        "statusCode": response.status_code,
        "headers": dict(response.headers),
        "body": response.get_data(as_text=True),
    }
