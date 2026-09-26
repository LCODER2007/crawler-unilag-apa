# DOCiD integration

URAAS talks to the Africa PID Alliance DOCiD platform in both directions, and
they are separate pieces of code with separate configuration. Confusing them
is the most likely way to cause damage here, so read this section first.

| Direction | Module | What it does | Writes to |
|---|---|---|---|
| **Pull** (ingest) | `uraas/services/docid_ingest.py` | Reads DOCiD's publications into URAAS | URAAS's database |
| **Push** (register) | `uraas/services/docid_client.py` | Registers URAAS records on the DOCiD platform | **DOCiD's platform** |

The pull direction cannot write to DOCiD. It has no auth, no POST and no
credentials, deliberately: an ingest must not be able to create a record on
someone else's platform by accident.

---

## Environments

| | Base URL | Notes |
|---|---|---|
| Demo | `https://docid-demo.africapidalliance.org/api/v1` | Default. 3,726 publications as of 2026-09-26 |
| Production | `https://docid-core.africapidalliance.org/api/v1` | Same API shape |

Interactive docs are at `/apidocs/` on either host, and the machine-readable
OpenAPI 2.0 spec at `/apispec_1.json` (180 endpoints).

**Reads need no authentication on either instance.** Verified live against
demo on 2026-09-26: `get-publications` and `get-publication/{id}` both return
200 with no `Authorization` header.

Point URAAS at an instance with `DOCID_INGEST_API_URL`. Change
`DOCID_SOURCE_LABEL` at the same time: it is stamped on every ingested
record's `source_repository` and is half of that record's stable identity, so
pointing at production while still labelled `DOCiD (demo)` would merge two
different corpora into one.

---

## What the API allows, and what that forces

Three properties of the API determine the whole design. They were measured,
not assumed.

### 1. There is no incremental filter

`get-publications` accepts `page`, `page_size`, `resource_type_id`, `sort` and
`order`. There is no `modified_since`, no `updated_after` and no cursor. Also
**only `sort=published` works** - `sort=title` returns an empty body.

So there are exactly two strategies available:

- **Backfill** walks oldest-first (`order=asc`). Ascending order is what makes
  offset paging safe: records are appended as they are published, so page 40
  keeps pointing at the same records for the whole run. A descending walk
  would shift every record one place down the moment anything new was
  published, silently skipping records.
- **Incremental** walks newest-first (`order=desc`) and stops at the first
  page containing nothing new. Stopping on a whole known page rather than the
  first known record leaves a page of overlap, which absorbs any reshuffling
  caused by records published mid-walk.

**The incremental walk only sees new records.** A record edited in place on
the platform keeps its original `published` timestamp and will never
resurface. Picking up edits needs either a `modified_since` filter upstream or
a periodic full re-ingest. This is the single most useful thing to ask the
Africa PID Alliance for.

### 2. One detail request per record is mandatory

The list response carries `id`, `title`, `docid`, `doi`, `published`,
`resource_type_id` and `owner`. It does **not** carry creators,
organisations or the abstract - the three things URAAS most needs. Those come
only from `get-publication/{id}`.

`tests/test_docid_ingest.py::test_index_rows_lack_the_fields_that_force_a_detail_call`
asserts this. If the platform ever adds those fields to the list response,
that test fails, and the ingest can collapse to one request per *page* - the
difference between weeks and hours at corpus scale. That is the second thing
worth asking for.

### 3. Nothing throttles us but us

No rate limiting was observed: twelve rapid requests returned twelve 200s,
with no `X-RateLimit-*` headers, no `Retry-After` and no 429. Measured costs:

| Call | Cost |
|---|---|
| `get-publications` at `page_size=100` | ~2.4s |
| `get-publications` at `page_size=1000` | ~5.7s (1000 is accepted) |
| `get-publication/{id}` | 0.7s to 1.6s depending on record size |

Deep paging did not degrade across the demo's 3,726 records, but that says
nothing about a corpus of millions, where offset paging typically does.

Because the platform will not protect itself from us, every request goes
through `DocIDReadClient._sleep_between()` (`DOCID_INGEST_DELAY_S`, default
0.2s per worker), and `docid_ingest_record` carries a Celery `rate_limit`.
Real concurrency is worker count times that. **Agree a rate with the Africa
PID Alliance before raising `--concurrency`.**

---

## Why Celery

One detail request per record. Measured end to end on 2026-09-26: **150
records in 103 seconds, or 0.69s per record**, including mapping, author
resolution and the database write.

| Corpus | Single-threaded | 4 workers | 16 workers |
|---|---|---|---|
| 3,726 (demo) | ~43 min | ~11 min | ~3 min |
| 1,000,000 | ~8 days | ~2 days | ~12 hours |

The worker columns assume the API sustains that concurrency, which has not
been agreed with the Africa PID Alliance and has not been tested. They are
the reason for a queue, not a promise.

Eight days of work cannot run in a web request, cannot be lost to a restart,
and cannot be parallelised by threads inside one gunicorn worker.
`uraas/tasks.py` is the Celery app.

### Task shape

The coordinator does O(1) work. `docid_backfill` asks the API for the total
page count and dispatches one task per page **without fetching the pages
itself**; each `docid_ingest_page` then fetches its own page and walks its own
records in-task.

Records are walked inside the page task rather than dispatched individually
on purpose: at corpus scale, one message per record is millions of messages
for no benefit, since the work is IO-bound on the same upstream either way.
100 records per page is roughly 70 seconds of work, which is a sane task
size.
`docid_ingest_record` still exists as a single-record task, for re-driving the
ids a page reports in `failed_ids`.

A failed record does not fail its page. It is counted, listed and skipped, so
one malformed payload in a corpus of millions cannot stall the ingest.

### Running without a broker

If `CELERY_BROKER_URL` is unset, the app runs `task_always_eager`: `.delay()`
executes inline and returns a finished result. Local development and the
Hugging Face Space therefore keep working unchanged - the Space has one
gunicorn worker, no Redis and no second process, so it could not run a worker
even if we wanted it to.

Eager mode preserves correctness, not scale. `POST /api/admin/docid/ingest/backfill`
**refuses an unbounded backfill** when there is no broker, because it would
run one upstream request per record inside the request thread; pass
`max_pages` to bound it, or start the real stack.

`REDIS_URL` is deliberately **not** accepted as a broker fallback. It is the
analytics cache's address and is set on developer machines where nothing is
listening; inheriting it would make `.delay()` queue work into a Redis that
does not exist - the task vanishes and the caller is told it was accepted.
Running inline is a safe failure; silently dropping work is not.

### Running with a broker

```bash
docker compose -f deploy/docker-compose.prod.yml up -d redis celery-worker celery-beat
```

`celery-beat` runs the hourly incremental catch-up. Exactly one beat container
must run - two would double every scheduled ingest.

---

## Record identity

Ingested records are upserted on **`(source_repository, source_record_id)`**,
where `source_record_id` is DOCiD's own integer publication id.

This pair exists because nothing else could carry an idempotent upsert:
`Item.id` is a local key that admin prune and clear-half-recrawl delete and
SQLite then reuses, and `doi` is absent on a large minority of records
(publication 4185, a real DSpace-harvested record, has none). Without it,
re-ingesting either duplicated records or overwrote the wrong one. It is also
exactly the external key `docs/PARTNER_API.md` invited partners to ask for.

DOI and URL are fallbacks, so an ingest **enriches** a paper URAAS already
crawled from OpenAlex rather than creating a second copy of it.

**Ingest never blanks an existing value.** A crawled record can carry an
abstract, a DOI or a citation count that the DOCiD copy lacks; writing DOCiD's
nulls over the top would destroy data on every sync.

## Field mapping

| DOCiD | URAAS `Item` |
|---|---|
| `id` | `source_record_id` |
| `document_docid` | `docid` |
| `document_title` | `title`, `dc_title` (truncated to 512) |
| `abstract_text`, else `document_description` | `abstract` |
| `doi` | `doi`, `dc_identifier_doi` |
| `handle_url` | `url`, `dc_identifier_uri`, `pid_source="handle"` |
| `published` (Unix epoch) | `publication_date`, `dc_date_issued` |
| `resource_type_id` | `content_type` |
| `owner`, else first organisation | `institution` |
| first organisation's ROR | `ror` |
| `collection_name` | `dc_subject` |
| `publication_creators[]` | `authors` (matched on `normalized_name`) |
| `openalex_id`, `citation_count` | `openalex_id`, `cited_by_count` |
| `open_access_url`, `open_access_status` | `pdf_url`, `dc_rights` |

Two traps worth naming:

- **`identifier_type` decides what `identifier` holds.** Organisations carry
  `ror`, `isni`, `ringgold` or `rrid` in the same field. Reading it blindly
  files an ISNI as a ROR and corrupts every institution-level metric that
  groups on `ror`.
- **Free text arrives as HTML.** `description` comes back as `<p>Desc</p>`; it
  is authored in a rich-text editor. Everything goes through the same
  `sanitize_text` the crawl pipeline uses, so ingested records read
  identically to crawled ones.
- **A source Handle wins over a minted ARK.** Records with a `handle_url` get
  `pid_source="handle"`, so URAAS does not mint an ARK over an identifier the
  source repository already assigned.

**Expect many records to have no creators at all.** Of the 150 oldest demo
records ingested during testing, only 2 carried any. That is DOCiD's data,
not a mapping bug - author-derived metrics over an ingested corpus will look
sparse, and the `records_with_creators` figure in coverage is there to make
that visible rather than surprising.

Authors are matched on `normalized_name` (lower-cased) exactly as
`uraas/pipelines/database.py` does. A different rule here would split one
person into two `Author` rows across the crawled and ingested halves of the
corpus, quietly halving their publication count and h-index.

---

## Endpoints

Read (partner-readable):

```
GET  /api/docid/ingest/coverage           local count, remote total, queue mode
GET  /api/docid/ingest/coverage?remote=0  local only, no call to DOCiD
```

Write (admin only - they hit the DOCiD API and write to our database):

```
POST /api/admin/docid/ingest/backfill     { "max_pages": 5, "page_size": 100, "start_page": 1 }
POST /api/admin/docid/ingest/incremental  { "max_pages": 5 }
POST /api/admin/docid/ingest/record/<id>  re-drive one record
```

`coverage` reports the remote total next to the local count, because "we hold
3,000 records" means nothing without knowing whether the source has 3,726 or
three million. It also reports `queue.eager`, so an operator can tell "queued
on a worker" from "ran inline and blocked the request".

---

## The circular-ingest guard

DOCiD pulls records from URAAS through the partner API, and URAAS now
ingests records from DOCiD. Nothing in either direction knows about the
other, so without a guard a DOCiD record would be served straight back to
DOCiD and re-ingested as though it were a UNILAG record - each side
crediting the other as the source, with no way to tell afterwards which of
them actually holds it.

`GET /api/papers/tree`, the enumeration endpoint a full partner pull starts
from, therefore excludes records whose `source_repository` starts with
`DOCiD` **for partner-key callers only**. A browser session sees everything:
looking at the ingested corpus is the entire point of ingesting it.

The match is on the prefix, not the exact label, so `DOCiD (demo)` and
`DOCiD (production)` are both covered by one rule and switching
`DOCID_SOURCE_LABEL` cannot leak records.

This guard lives at the partner API boundary
(`PARTNER_EXCLUDED_SOURCE_PREFIXES` in `uraas/dashboard/app.py`), not in the
ingest and not in the analytics engine, because it is a statement about who
is asking rather than about the data.

## Open questions for the Africa PID Alliance

In priority order:

1. **A `modified_since` (or `updated_after`) filter on `get-publications`.**
   Without it, edits to existing records are invisible to an incremental sync
   and the only way to catch them is a full re-ingest.
2. **Creators, organisations and abstract in the list response**, or a bulk
   detail endpoint. This is the difference between one request per record and
   one per page - hours instead of weeks at corpus scale.
3. **An agreed request rate.** There is none advertised and none enforced. We
   are currently self-limiting at roughly 5 requests/second/worker.
4. **Whether offset paging holds up past a few thousand records**, or whether
   a cursor will be needed.
