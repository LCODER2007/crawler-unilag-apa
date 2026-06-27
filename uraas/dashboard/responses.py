"""
Standard API response helpers for new URAAS endpoints.

Envelope shape:
    {"status": "success", "data": ..., "narrative": "...",
     "methodology": {...}, "benchmark": {...}}

Older endpoints keep their bare payloads until migrated (their JS consumers
parse those shapes directly); all NEW endpoints must use api_ok/api_error.
"""

import csv
import io
from typing import Iterable, Optional

from flask import Response, jsonify, stream_with_context


def api_ok(
    data,
    *,
    narrative: Optional[str] = None,
    methodology_key: Optional[str] = None,
    benchmark: Optional[dict] = None,
    **extra,
) -> Response:
    """Standard success envelope. methodology_key is resolved from
    uraas.config.methodology.METHODOLOGY so the chart tooltip and the
    endpoint always agree."""
    payload = {"status": "success", "data": data}
    if narrative:
        payload["narrative"] = narrative
    if methodology_key:
        from uraas.config.methodology import METHODOLOGY

        method = METHODOLOGY.get(methodology_key)
        if method:
            payload["methodology"] = {"key": methodology_key, **method}
            if benchmark is None:
                benchmark = method.get("benchmark")
    if benchmark:
        payload["benchmark"] = benchmark
    payload.update(extra)
    return jsonify(payload)


def api_error(message: str, status: int = 500, **extra) -> Response:
    payload = {"status": "error", "message": message}
    payload.update(extra)
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def csv_response(rows: Iterable[list], filename: str) -> Response:
    """Streaming CSV download. `rows` is any iterable of lists (header first);
    pass a generator for large exports so nothing is held in memory."""

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
