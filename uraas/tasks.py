"""
Celery application and background tasks.

Why this exists: a DOCiD ingest costs one detail request per record at about
1.6 seconds each. The demo corpus of 3,726 records is roughly 100 minutes
sequentially; a production corpus in the millions is weeks. That cannot live
in a web request, cannot be lost to a restart, and cannot be parallelised by
threads inside a single gunicorn worker.

Degrading without a broker
--------------------------
If CELERY_BROKER_URL (or REDIS_URL) is unset, the app is configured
`task_always_eager`, so `.delay()` runs the task inline and returns a
finished result. That keeps local development and the single-container
Hugging Face Space working unchanged - the Space has one gunicorn worker,
no Redis and no second process, so it could not run a worker even if we
wanted it to. Eager mode is correctness-preserving but not scale-preserving:
a real backfill needs the Compose stack (deploy/docker-compose.prod.yml),
which brings up Redis and dedicated worker containers.

Task shape
----------
The coordinator does O(1) work: it asks the API for the total page count and
dispatches one task per page, without fetching the pages itself. Each page
task then fetches its own page and walks its own records. That keeps the
message count at total/page_size rather than one message per record, and
keeps each task at a sane size - 100 records is about 160 seconds of work.

A failed record does not fail its page: it is counted and skipped, so one
bad payload in a corpus of millions cannot stall the ingest.
"""

import logging
from typing import Dict, List, Optional

from celery import Celery
from celery.utils.log import get_task_logger

from uraas.config import config

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)


def _broker_url() -> str:
    """The broker to use, or "" when there is none.

    Only CELERY_BROKER_URL counts. REDIS_URL is deliberately NOT accepted as
    a fallback even though the Compose stack defines one: REDIS_URL is the
    analytics cache's address and is set in .env on developer machines where
    nothing is listening, so inheriting it would make `.delay()` queue work
    into a Redis that does not exist - the task vanishes and the caller is
    told it was accepted. Running inline is the safe failure; silently
    dropping work is not. deploy/docker-compose.prod.yml sets
    CELERY_BROKER_URL explicitly.
    """
    return config.CELERY_BROKER_URL or ""


BROKER_URL = _broker_url()
EAGER = not BROKER_URL

celery_app = Celery("uraas", broker=BROKER_URL or None)
celery_app.conf.update(
    result_backend=(config.CELERY_RESULT_BACKEND or BROKER_URL or None),
    task_always_eager=EAGER,
    task_eager_propagates=False,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A worker killed mid-ingest must not silently drop the page it held.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # An ingest page is ~160s of work; without a ceiling a hung upstream
    # request would hold a worker slot indefinitely.
    task_soft_time_limit=1800,
    task_time_limit=2100,
    result_expires=86400,
)

if EAGER:
    logger.info(
        "Celery has no broker configured - running tasks eagerly, in process. "
        "Set CELERY_BROKER_URL (or REDIS_URL) and run a worker for real "
        "background execution."
    )


def queue_status() -> Dict:
    """Whether real background execution is available, for the API to report.

    An operator needs to know the difference between "the backfill is
    queued" and "the backfill ran inline and blocked the request", and that
    difference is invisible from the task result alone.
    """
    return {
        "eager": EAGER,
        "broker_configured": bool(BROKER_URL),
        # Never leak the broker URL itself - it routinely carries a password.
        "broker_scheme": BROKER_URL.split("://", 1)[0] if BROKER_URL else None,
    }


# -- DOCiD ingest -------------------------------------------------------------


@celery_app.task(
    name="uraas.docid.ingest_record",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    rate_limit="60/m",
)
def docid_ingest_record(self, publication_id) -> Dict:
    """Fetch and store one DOCiD publication.

    Separate from the page task so a record that failed its page can be
    retried on its own, and so a single record can be refreshed on demand.
    """
    from uraas.services.docid_ingest import DocIDIngestError, ingest_record

    try:
        return ingest_record(publication_id)
    except DocIDIngestError as exc:
        task_logger.warning("docid record %s failed: %s", publication_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="uraas.docid.ingest_page",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def docid_ingest_page(
    self,
    page: int,
    page_size: Optional[int] = None,
    order: str = "asc",
    known_ids: Optional[List[str]] = None,
) -> Dict:
    """Fetch one index page and ingest every record on it.

    Records are walked in-task rather than dispatched individually: at corpus
    scale one message per record is millions of messages for no benefit,
    since the work is IO-bound on the same upstream either way.

    `known_ids` lets the incremental walk skip records already held without a
    database round trip per record.
    """
    from uraas.services.docid_ingest import (
        DocIDIngestError,
        DocIDReadClient,
        upsert_publication,
    )

    stats = {
        "page": page,
        "records": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "failed_ids": [],
    }
    skip = set(known_ids or [])
    client = DocIDReadClient()

    try:
        envelope = client.list_publications(page=page, page_size=page_size, order=order)
    except DocIDIngestError as exc:
        task_logger.warning("docid page %s list failed: %s", page, exc)
        raise self.retry(exc=exc)

    for row in envelope.get("data") or []:
        remote_id = row.get("id")
        if remote_id is None:
            continue
        stats["records"] += 1
        if str(remote_id) in skip:
            stats["skipped"] += 1
            continue
        try:
            payload = client.get_publication(remote_id)
            result = upsert_publication(payload)
            stats[result["action"]] = stats.get(result["action"], 0) + 1
        except Exception as exc:
            # One malformed record must not abort a page. Record it and move
            # on; failed_ids can be re-driven through docid_ingest_record.
            stats["failed"] += 1
            if len(stats["failed_ids"]) < 50:
                stats["failed_ids"].append(remote_id)
            task_logger.warning("docid record %s on page %s: %s", remote_id, page, exc)

    task_logger.info("docid page %s done: %s", page, stats)
    return stats


@celery_app.task(name="uraas.docid.backfill")
def docid_backfill(
    start_page: int = 1,
    max_pages: Optional[int] = None,
    page_size: Optional[int] = None,
) -> Dict:
    """Dispatch a full ingest of the DOCiD corpus.

    Walks oldest-first (`order=asc`). Ascending order is what makes offset
    paging safe here: records are appended as they are published, so a page
    number keeps pointing at the same records for the duration of the run.
    A descending walk would shift every record one place down the moment
    anything new was published, silently skipping records.

    This dispatches and returns; it does not wait. Poll ingest coverage to
    follow progress.
    """
    from uraas.services.docid_ingest import DocIDReadClient

    size = page_size or config.DOCID_INGEST_PAGE_SIZE
    client = DocIDReadClient()
    first = client.list_publications(page=start_page, page_size=size, order="asc")
    pagination = first.get("pagination") or {}
    total_pages = int(pagination.get("total_pages") or 0)
    total = int(pagination.get("total") or 0)

    last_page = total_pages
    if max_pages:
        last_page = min(total_pages, start_page + max_pages - 1)

    dispatched = 0
    for page in range(start_page, last_page + 1):
        docid_ingest_page.delay(page=page, page_size=size, order="asc")
        dispatched += 1

    summary = {
        "remote_total": total,
        "total_pages": total_pages,
        "page_size": size,
        "start_page": start_page,
        "last_page": last_page,
        "pages_dispatched": dispatched,
        **queue_status(),
    }
    task_logger.info("docid backfill dispatched: %s", summary)
    return summary


@celery_app.task(name="uraas.docid.incremental")
def docid_incremental(max_pages: int = 5, page_size: Optional[int] = None) -> Dict:
    """Catch up on records published since the last ingest.

    The API has no `modified_since` parameter and no cursor, so the only
    incremental strategy available is to walk newest-first and stop once a
    page contains nothing new. `max_pages` bounds that walk so a misconfigured
    watermark cannot turn a catch-up into a full re-ingest.

    This only sees *new* records. A record edited in place on the platform
    keeps its original `published` timestamp and will not resurface here - # picking those up needs either a modified_since filter upstream or a
    periodic full re-ingest.
    """
    from uraas.services.docid_ingest import (
        DocIDReadClient,
        known_source_ids,
        upsert_publication,
    )

    size = page_size or config.DOCID_INGEST_PAGE_SIZE
    known = known_source_ids()
    client = DocIDReadClient()
    stats = {
        "pages_walked": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "stopped_early": False,
    }

    for page in range(1, max_pages + 1):
        envelope = client.list_publications(page=page, page_size=size, order="desc")
        rows = envelope.get("data") or []
        if not rows:
            break
        stats["pages_walked"] += 1
        new_on_page = 0
        for row in rows:
            remote_id = row.get("id")
            if remote_id is None:
                continue
            if str(remote_id) in known:
                stats["skipped"] += 1
                continue
            new_on_page += 1
            try:
                payload = client.get_publication(remote_id)
                result = upsert_publication(payload)
                stats[result["action"]] = stats.get(result["action"], 0) + 1
                known.add(str(remote_id))
            except Exception as exc:
                stats["failed"] += 1
                task_logger.warning("docid incremental %s: %s", remote_id, exc)
        # A page that was entirely records we already hold means the walk has
        # reached the watermark. Stopping on the first such page rather than
        # the first known record leaves a page of overlap, which absorbs the
        # reshuffling caused by anything published mid-walk.
        if new_on_page == 0:
            stats["stopped_early"] = True
            break

    task_logger.info("docid incremental: %s", stats)
    return stats


# Scheduled catch-up. Only runs where celery beat runs, which is the Compose
# stack - the Space has no scheduler, so its records stay at whatever the
# last manual ingest left.
celery_app.conf.beat_schedule = {
    "docid-incremental-hourly": {
        "task": "uraas.docid.incremental",
        "schedule": 3600.0,
        "kwargs": {"max_pages": 5},
    },
}
