"""
Shared OpenAlex HTTP helper — single place for the api_key / mailto params.

Used by the citation tracker and the backfill scripts (the Scrapy spider
builds its own URLs but reads the same Config values).
"""

import logging
from typing import Optional

import requests

from uraas.config import config

OPENALEX_API = "https://api.openalex.org"

logger = logging.getLogger(__name__)


def oa_params(extra: Optional[dict] = None) -> dict:
    """Base query params: polite mailto + api_key when configured."""
    params = {"mailto": config.OPENALEX_MAILTO}
    if config.OPENALEX_API_KEY:
        params["api_key"] = config.OPENALEX_API_KEY
    if extra:
        params.update(extra)
    return params


def oa_get(path: str, params: Optional[dict] = None, timeout: int = 30) -> Optional[dict]:
    """GET an OpenAlex endpoint ('/works', '/works/W123', or a full URL).

    Returns parsed JSON, or None on any failure (callers treat missing data
    as 'not yet enriched', never as fatal)."""
    url = path if path.startswith("http") else f"{OPENALEX_API}{path}"
    try:
        resp = requests.get(url, params=oa_params(params), timeout=timeout)
        if resp.status_code == 429:
            logger.warning("OpenAlex rate limited (429): %s", url)
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("OpenAlex request failed (%s): %s", url, e)
        return None
