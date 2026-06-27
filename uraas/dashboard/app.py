import csv
import io
import json
import logging
import os
import re
import subprocess
import threading

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_socketio import SocketIO
from sqlalchemy import desc, extract, func, or_
from sqlalchemy.orm import selectinload

from uraas.analytics.engine import analytics
from uraas.config import config
from uraas.database import (
    Author,
    Collection,
    Community,
    File,
    Item,
    SessionLocal,
    db_year,
    db_year_month,
)
from uraas.dashboard.auth import (
    ADMIN,
    check_credentials,
    clamped_int,
    current_role,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from uraas.dashboard.responses import api_error, api_ok, csv_response
from uraas.production_config import ProductionConfig
from uraas.utils.analytics_cache import analytics_cache

# Fail fast on insecure production config before the app even binds.
config.validate()

app = Flask(__name__)
app.config["SECRET_KEY"] = config.DASHBOARD_SECRET_KEY
# Session-cookie hardening applies in every environment (SECURE only where TLS
# is present, i.e. production) so it is not Render-specific.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.is_production(),
)
# Apply production hardening at import time so it also runs under gunicorn
# (the __main__ block below never executes in a WSGI deployment).
ProductionConfig.apply_config(app)

# SocketIO: restrict the handshake to an explicit origin allowlist (no wildcard).
socketio = SocketIO(
    app,
    cors_allowed_origins=config.cors_origins(),
    async_mode="threading",
)
logger = logging.getLogger(__name__)
crawler_process = None
crawler_lock = threading.Lock()

# Rate limiter — in-memory storage (no Redis dep). Limits login to 10 attempts
# per minute to prevent brute-force attacks on admin/viewer credentials.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],  # No global limit; only login is rate-limited.
    storage_uri="memory://",
)

# ── Access control (fail-closed) ───────────────────────────────────────────
# Everything is gated by default. Endpoints are authorised by *endpoint name*
# (function name) so path params don't matter and any NEW route is protected
# until explicitly listed here.
#
#   PUBLIC_ENDPOINTS — reachable without a session (login page, health, static).
#   ADMIN_ENDPOINTS  — require role == admin (crawler, mutations, bulk exports,
#                      staff directory PII). Everything else needs any login.
PUBLIC_ENDPOINTS = {"login", "logout", "health_check", "api_version", "static"}
ADMIN_ENDPOINTS = {
    "start_crawler",
    "stop_crawler",
    "crawler_status",
    "flush_analytics_cache",
    "update_citations",
    "bulk_update_citations",
    "export_csv",
    "export_bibtex",
    "export_special_collections_csv",
    "alignment_export_csv",
    "collaboration_export_csv",
    "citations_velocity_csv",
    "staff_directory",
}


@app.before_request
def _enforce_authentication():
    endpoint = request.endpoint
    # Unknown endpoint (404s) and explicit public routes pass through.
    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None
    role = current_role()
    if not role:
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        return redirect(url_for("login", next=request.path))
    if endpoint in ADMIN_ENDPOINTS and role != ADMIN:
        return jsonify({"status": "error", "message": "Administrator access required"}), 403
    return None


def crawler_monitor(process):
    global crawler_process
    try:
        for line in iter(process.stdout.readline, b""):
            with crawler_lock:
                if crawler_process is None or crawler_process != process:
                    break
            line_decoded = line.decode("utf-8", errors="replace").strip()
            if not line_decoded:
                continue
            if line_decoded.startswith("[INIT]"):
                socketio.emit(
                    "crawl_status", {"status": "initializing", "message": line_decoded}
                )
                socketio.emit("terminal_output", {"line": line_decoded})
            elif "URAAS_DOWNLOAD:" in line_decoded:
                socketio.emit("crawl_status", {"status": "running"})
                try:
                    title = line_decoded.split("URAAS_DOWNLOAD:", 1)[-1].strip()
                    socketio.emit("crawl_progress", {"title": title})
                except Exception:
                    pass
                socketio.emit("terminal_output", {"line": line_decoded})
            else:
                socketio.emit("terminal_output", {"line": line_decoded})
    except Exception:
        pass
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()
        with crawler_lock:
            if crawler_process == process:
                crawler_process = None
        analytics_cache.invalidate_all()  # Flush stale analytics after crawl
        socketio.emit("crawl_status", {"status": "stopped"})


@app.context_processor
def inject_asset_version():
    """Cache-bust static assets by their file mtime so browsers always load
    the latest JS/CSS after a deploy or edit (no more stale cached app.js)."""

    def asset_version(filename):
        try:
            path = os.path.join(app.static_folder, filename)
            return str(int(os.path.getmtime(path)))
        except OSError:
            return "1"

    return {"asset_version": asset_version}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"], error_message="Too many login attempts — wait 60 seconds.")
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role = check_credentials(username, password)
        if role:
            session.clear()
            session["role"] = role
            session["user"] = username
            session.permanent = True
            dest = request.args.get("next") or url_for("index")
            # Prevent open redirect: reject any URL with a scheme or netloc
            # (this blocks both http://evil.com AND //evil.com style redirects).
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(dest)
            if _parsed.scheme or _parsed.netloc or not dest.startswith("/"):
                dest = url_for("index")
            return redirect(dest)
        # Generic message — no user enumeration.
        return render_template("login.html", error="Invalid username or password"), 401
    if current_role():
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.after_request
def set_security_headers(response):
    """Defense-in-depth headers. CSP allows only the CDNs the dashboard uses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
        "https://unpkg.com https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://cdnjs.cloudflare.com https://fonts.googleapis.com https://unpkg.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://api.openalex.org https://api.crossref.org "
        "https://ror.org https://*.basemaps.cartocdn.com; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'none'"
    )
    if config.is_production():
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@socketio.on("connect")
def _socket_auth():
    """Reject WebSocket connections that are not from a logged-in session,
    so the crawler event stream can't be driven anonymously."""
    if not session.get("role"):
        return False
    return True


@app.route("/ark:/<naan>/<path:name>")
def resolve_ark(naan, name):
    """Local ARK resolver (ARK spec: resolver base + '/' + ark).

    Redirects to the dashboard with the paper modal auto-opened; the ARK
    'inflection' suffix '?' / '?info' returns the metadata record as JSON."""
    from flask import redirect

    ark = f"ark:/{naan}/{name}"
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(ark=ark).first()
        if not item:
            return jsonify({"error": "ARK not found", "ark": ark}), 404
        # ARK inflection: '?info' / '?json' returns the metadata record. (A bare
        # '?' is the spec's brief-metadata inflection, but Flask's full_path
        # always appends '?', so it can't be told apart from a plain resolve —
        # we require the explicit suffix.)
        wants_info = "info" in request.args or "json" in request.args
        if wants_info:
            return jsonify(
                {
                    "ark": ark,
                    "docid": item.docid or "",
                    "doi": item.doi or "",
                    "title": item.title or "",
                    "institution": item.institution or "",
                    "publication_date": (
                        item.publication_date.isoformat()
                        if item.publication_date
                        else None
                    ),
                    "authors": [a.name for a in item.authors],
                    "resolver": "URAAS / Africa PID Alliance",
                }
            )
        return redirect(f"/?paper={item.id}")
    except Exception as e:
        logger.error("resolve_ark %s: %s", ark, e)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        session.close()


@app.route("/api/methodology")
def get_methodology():
    """Full per-metric methodology dictionary — feeds the ⓘ tooltips.

    Every metric on the dashboard documents its formula, data source and
    caveats here so each number can be audited (open-methodology principle)."""
    from uraas.config.methodology import METHODOLOGY

    return jsonify({"status": "success", "data": METHODOLOGY})


@app.route("/api/stats")
def get_stats():
    try:
        return jsonify(
            {
                "status": "success",
                "top_authors": analytics.get_top_authors(limit=5),
                "network_edges": analytics.get_department_collaboration_network(),
            }
        )
    except Exception as e:
        logger.error("get_stats: %s", e)
        return jsonify({"status": "error", "top_authors": [], "network_edges": []}), 500


@app.route("/api/papers/tree")
def papers_tree():
    try:
        institution = request.args.get("institution", None)
        return jsonify(
            {
                "status": "success",
                "data": analytics.get_papers_by_faculty_and_department(
                    institution=institution
                ),
            }
        )
    except Exception as e:
        logger.error("papers_tree: %s", e)
        return jsonify({"status": "error", "data": []}), 500


@app.route("/api/papers/<int:item_id>")
def get_paper(item_id):
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(id=item_id).first()
        if not item:
            return jsonify({"error": "Paper not found"}), 404
        file_record = session.query(File).filter_by(item_id=item_id).first()
        collections = [
            {
                "id": c.id,
                "name": c.name,
                "faculty": c.community.name if c.community else "Unknown",
            }
            for c in item.collections
        ]
        return jsonify(
            {
                "id": item.id,
                "docid": item.docid or "",
                "ark": item.ark or "",
                "ark_url": f"/{item.ark}" if item.ark else "",
                "cited_by_count": item.cited_by_count or 0,
                "african_citation_share": item.african_citation_share,
                "counts_by_year": (
                    json.loads(item.counts_by_year) if item.counts_by_year else []
                ),
                "coauthor_countries": item.coauthor_countries or "",
                "is_intra_african": bool(item.is_intra_african),
                "title": item.title or "Untitled",
                "abstract": item.abstract or "",
                "doi": item.doi or "",
                "url": item.url or "",
                "pdf_url": item.pdf_url or "",
                "publication_date": (
                    item.publication_date.isoformat() if item.publication_date else None
                ),
                "source_repository": item.source_repository or "",
                "authors": [{"name": a.name} for a in item.authors],
                "collections": collections,
                "dc": {
                    "title": item.dc_title or "",
                    "date_issued": item.dc_date_issued or "",
                    "identifier_uri": item.dc_identifier_uri or "",
                    "identifier_doi": item.dc_identifier_doi or "",
                    "description_provenance": item.dc_description_provenance or "",
                    "rights": item.dc_rights or "",
                },
                "file": (
                    {
                        "has_local_pdf": file_record is not None,
                        "access_policy": (
                            file_record.access_policy if file_record else None
                        ),
                        "download_url": (
                            f"/api/papers/{item_id}/download" if file_record else None
                        ),
                        "sha256": file_record.sha256_hash if file_record else None,
                    }
                    if file_record
                    else {"has_local_pdf": False}
                ),
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )
    except Exception as e:
        logger.error("get_paper %s: %s", item_id, e)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        session.close()


def _is_open_access(item, file_record) -> bool:
    """Open-access when the item's rights say so OR the file is policy-Public."""
    rights = (item.dc_rights or "").lower() if item else ""
    if "openaccess" in rights.replace("/", "").replace("-", ""):
        return True
    if file_record and (file_record.access_policy or "").lower() == "public":
        return True
    return False


@app.route("/api/papers/<int:item_id>/download")
def download_paper(item_id):
    session = SessionLocal()
    try:
        file_record = session.query(File).filter_by(item_id=item_id).first()
        if not file_record:
            return jsonify({"error": "PDF not found"}), 404
        item = session.query(Item).filter_by(id=item_id).first()

        # Copyright gate: viewers may only download verified open-access files;
        # restricted items are admin-only (see PRIVACY_NOTICE / readiness doc).
        if not _is_open_access(item, file_record) and current_role() != ADMIN:
            return (
                jsonify(
                    {
                        "error": "This item is not open access.",
                        "message": (
                            "Full text is restricted by the publisher's licence. "
                            "Use the publisher or open-access link on the record."
                        ),
                    }
                ),
                403,
            )

        # Resolve and contain the path under the project/storage root so a stored
        # path can never escape via traversal into arbitrary files.
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        file_path = file_record.file_path
        if not os.path.isabs(file_path):
            file_path = os.path.join(project_root, file_path)
        real_path = os.path.realpath(file_path)
        allowed_roots = [
            os.path.realpath(project_root),
            os.path.realpath(config.STORAGE_PATH),
        ]
        if not any(
            os.path.commonpath([real_path, root]) == root for root in allowed_roots
        ):
            logger.warning("download_paper %s: path escape blocked: %s", item_id, real_path)
            return jsonify({"error": "Access denied"}), 403
        if not os.path.exists(real_path):
            return jsonify({"error": "PDF file missing from storage"}), 404

        filename = (
            f"{item.title[:50]}.pdf" if item and item.title else f"paper_{item_id}.pdf"
        )
        filename = "".join(
            c for c in filename if c.isalnum() or c in (" ", "-", "_", ".")
        ).strip()
        return send_file(
            real_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.error("download_paper %s: %s", item_id, e)
        return jsonify({"error": "Failed to download PDF"}), 500
    finally:
        session.close()


@app.route("/api/papers/<int:item_id>/bibtex")
def export_single_bibtex(item_id):
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(id=item_id).first()
        if not item:
            return jsonify({"error": "Paper not found"}), 404
        authors = [a.name for a in item.authors]
        first_last = authors[0].split()[-1] if authors else "Unknown"
        year = str(item.publication_date.year) if item.publication_date else "nd"
        key = re.sub(r"[^a-zA-Z0-9]", "", f"{first_last}{year}")
        author_str = " and ".join(authors) if authors else "Unknown"
        title = (item.title or "Untitled").replace("{", "").replace("}", "")
        doi_line = f"  doi = {{{item.doi}}},\n" if item.doi else ""
        url_line = f"  url = {{{item.url}}},\n" if item.url else ""
        # Persistent identifiers — ARK is resolvable even without a DOI.
        note_bits = []
        if item.ark:
            note_bits.append(f"ARK: {item.ark}")
        if item.docid:
            note_bits.append(f"DocID: {item.docid}")
        note_line = f"  note = {{{'; '.join(note_bits)}}},\n" if note_bits else ""
        institution = (item.institution or "").strip() or "Unknown"
        bibtex = (
            f"@article{{{key},\n  title = {{{title}}},\n  author = {{{author_str}}},\n  year = {{{year}}},\n  institution = {{{institution}}},\n"
            + doi_line
            + url_line
            + note_line
            + "}"
        )
        return Response(
            bibtex,
            mimetype="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=paper_{item_id}.bib"
            },
        )
    except Exception as e:
        logger.error("bibtex %s: %s", item_id, e)
        return jsonify({"error": "Export failed"}), 500
    finally:
        session.close()


@app.route("/api/analytics/overview")
def analytics_overview():
    session = SessionLocal()
    institution = request.args.get("institution")
    try:
        q_item = session.query(Item)
        if institution and institution.lower() != "all":
            q_item = q_item.filter(Item.institution == institution)

        total = q_item.count()
        if total == 0:
            return jsonify(
                {
                    "total_papers": 0,
                    "total_authors": 0,
                    "total_faculties": 0,
                    "open_access_papers": 0,
                    "papers_with_local_pdf": 0,
                    "oa_percentage": 0,
                }
            )

        item_ids_query = q_item.with_entities(Item.id)

        q_author = session.query(Author).join(Author.items).filter(Item.id.in_(item_ids_query))
        q_comm = session.query(Community).filter(
            Community.collections.any(Collection.items.any(Item.id.in_(item_ids_query)))
        )
        q_file = session.query(File).filter(File.item_id.in_(item_ids_query))

        authors = q_author.distinct().count()
        faculties = q_comm.distinct().count()
        oa = q_item.filter(Item.dc_rights.like("%openAccess%")).count()
        pdfs = q_file.count()

        return jsonify(
            {
                "total_papers": total,
                "total_authors": authors,
                "total_faculties": faculties,
                "open_access_papers": oa,
                "papers_with_local_pdf": pdfs,
                "oa_percentage": round((oa / total * 100) if total else 0, 1),
            }
        )
    except Exception as e:
        logger.error("analytics_overview: %s", e)
        return (
            jsonify(
                {
                    "total_papers": 0,
                    "total_authors": 0,
                    "total_faculties": 0,
                    "open_access_papers": 0,
                    "papers_with_local_pdf": 0,
                    "oa_percentage": 0,
                }
            ),
            500,
        )
    finally:
        session.close()


@app.route("/api/analytics/publications-by-year")
def publications_by_year():
    institution = request.args.get("institution")
    return jsonify(analytics.get_publications_by_year(institution=institution))


@app.route("/api/analytics/papers-by-faculty")
def papers_by_faculty():
    institution = request.args.get("institution")
    return jsonify(analytics.get_papers_by_faculty(institution=institution))


@app.route("/api/analytics/top-authors")
def top_authors_analytics():
    limit = clamped_int("limit", 15, 1, 200)
    institution = request.args.get("institution")
    return jsonify(
        analytics.get_authors_by_papers(limit=limit, institution=institution)
    )


@app.route("/api/analytics/open-access-breakdown")
def oa_breakdown():
    institution = request.args.get("institution")
    return jsonify(analytics.get_open_access_breakdown(institution=institution))


@app.route("/api/analytics/recent-papers")
def recent_papers():
    limit = clamped_int("limit", 10, 1, 50)
    session = SessionLocal()
    try:
        items = session.query(Item).order_by(desc(Item.created_at)).limit(limit).all()
        return jsonify(
            [
                {
                    "id": i.id,
                    "title": i.title,
                    "doi": i.doi,
                    "authors": [a.name for a in i.authors[:3]],
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                    "is_oa": "openAccess" in (i.dc_rights or ""),
                }
                for i in items
            ]
        )
    finally:
        session.close()


@app.route("/api/analytics/growth-rate")
def growth_rate():
    institution = request.args.get("institution")
    # Backward compatibility with JS which expects 'session' instead of 'month'
    data = analytics.get_institutional_growth(institution=institution)
    return jsonify([{"session": d["month"], "count": d["count"]} for d in data])


@app.route("/api/analytics/timeline")
def timeline():
    institution = request.args.get("institution")
    return jsonify(analytics.get_timeline_data(institution=institution))


@app.route("/api/analytics/papers-by-year-faculty")
def papers_by_year_faculty():
    session = SessionLocal()
    try:
        rows = (
            session.query(
                db_year(Item.publication_date).label("year"),
                Community.name.label("faculty"),
                func.count(Item.id).label("count"),
            )
            .join(Item.collections)
            .join(Collection.community)
            .filter(Item.publication_date.isnot(None))
            .group_by("year", Community.name)
            .order_by("year")
            .all()
        )
        return jsonify(
            [
                {"year": int(r.year), "faculty": r.faculty, "count": r.count}
                for r in rows
                if r.year
            ]
        )
    finally:
        session.close()


@app.route("/api/analytics/faculty-oa-breakdown")
def faculty_oa_breakdown():
    """Phase 7 fix: group-by aggregate, no per-faculty item loads."""
    institution = request.args.get("institution")
    session = SessionLocal()
    try:
        # Two aggregate queries instead of N item fetches
        base_q = (
            session.query(
                Community.name,
                func.count(Item.id).label("total"),
            )
            .join(Item.collections)
            .join(Collection.community)
        )
        oa_q = (
            session.query(
                Community.name,
                func.count(Item.id).label("oa"),
            )
            .join(Item.collections)
            .join(Collection.community)
            .filter(Item.dc_rights.like("%openAccess%"))
        )
        if institution:
            inst_name = analytics._resolve_institution_name(institution)
            if inst_name:
                base_q = base_q.filter(Item.institution.ilike(f"%{inst_name}%"))
                oa_q = oa_q.filter(Item.institution.ilike(f"%{inst_name}%"))

        totals = {row.name: row.total for row in base_q.group_by(Community.name).all()}
        oas = {row.name: row.oa for row in oa_q.group_by(Community.name).all()}

        return jsonify(
            [
                {
                    "faculty": name,
                    "oa": oas.get(name, 0),
                    "restricted": totals[name] - oas.get(name, 0),
                }
                for name in totals
            ]
        )
    except Exception as e:
        logger.error("faculty_oa_breakdown: %s", e)
        return jsonify([])
    finally:
        session.close()


@app.route("/api/analytics/impact-metrics")
def impact_metrics():
    session = SessionLocal()
    institution = request.args.get("institution")
    try:
        inst_name = (
            analytics._resolve_institution_name(institution) if institution else None
        )

        q_item = session.query(Item)
        if inst_name:
            q_item = q_item.filter(Item.institution.ilike(f"%{inst_name}%"))

        total = q_item.count()
        oa = q_item.filter(Item.dc_rights.like("%openAccess%")).count()
        with_doi = q_item.filter(Item.doi.isnot(None)).count()

        q_file = session.query(File)
        if inst_name:
            q_file = q_file.join(File.item).filter(
                Item.institution.ilike(f"%{inst_name}%")
            )
        with_pdf = q_file.count()

        q_years = session.query(db_year(Item.publication_date)).filter(
            Item.publication_date.isnot(None)
        )
        if inst_name:
            q_years = q_years.filter(Item.institution.ilike(f"%{inst_name}%"))
        years = q_years.distinct().count()

        return jsonify(
            {
                "total_papers": total,
                "open_access_papers": oa,
                "oa_rate": round(oa / total * 100, 1) if total else 0,
                "papers_with_doi": with_doi,
                "doi_rate": round(with_doi / total * 100, 1) if total else 0,
                "papers_with_local_pdf": with_pdf,
                "pdf_rate": round(with_pdf / total * 100, 1) if total else 0,
                "years_covered": years,
            }
        )
    except Exception as e:
        logger.error("impact_metrics: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/analytics/search")
def analytics_search():
    q = request.args.get("q", "").strip()
    faculty = request.args.get("faculty", "").strip()
    year_from = request.args.get("year_from", type=int)
    year_to = request.args.get("year_to", type=int)
    oa_only = request.args.get("oa_only", "").lower() == "true"
    limit = clamped_int("limit", 50, 1, 200)
    session = SessionLocal()
    try:
        q_obj = session.query(Item)
        if q:
            author_subq = (
                session.query(Item.id)
                .join(Item.authors)
                .filter(Author.name.ilike(f"%{q}%"))
                .subquery()
            )
            q_obj = q_obj.filter(
                or_(
                    Item.title.ilike(f"%{q}%"),
                    Item.abstract.ilike(f"%{q}%"),
                    Item.doi.ilike(f"%{q}%"),
                    Item.id.in_(author_subq),
                )
            )
        if faculty:
            q_obj = (
                q_obj.join(Item.collections)
                .join(Collection.community)
                .filter(Community.name.ilike(f"%{faculty}%"))
            )
        if year_from:
            q_obj = q_obj.filter(db_year(Item.publication_date) >= str(year_from))
        if year_to:
            q_obj = q_obj.filter(db_year(Item.publication_date) <= str(year_to))
        if oa_only:
            q_obj = q_obj.filter(Item.dc_rights.like("%openAccess%"))
        items = q_obj.order_by(desc(Item.created_at)).limit(limit).all()
        return jsonify(
            [
                {
                    "id": i.id,
                    "title": i.title,
                    "doi": i.doi,
                    "abstract_snippet": (
                        (i.abstract or "")[:200]
                        if q and i.abstract and q.lower() in (i.abstract or "").lower()
                        else None
                    ),
                    "authors": [a.name for a in i.authors[:4]],
                    "year": i.publication_date.year if i.publication_date else None,
                    "is_oa": "openAccess" in (i.dc_rights or ""),
                    "faculty": (
                        i.collections[0].community.name if i.collections else None
                    ),
                }
                for i in items
            ]
        )
    finally:
        session.close()


@app.route("/api/analytics/faculties")
def list_faculties():
    session = SessionLocal()
    institution = request.args.get("institution")
    try:
        inst_name = (
            analytics._resolve_institution_name(institution) if institution else None
        )
        q = session.query(Community.name).order_by(Community.name)
        if inst_name:
            q = q.filter(
                Community.institution.ilike(f"%{inst_name}%")
                | Community.name.ilike(f"%{inst_name}%")
            )
        rows = q.all()
        return jsonify([r[0] for r in rows])
    finally:
        session.close()


@app.route("/api/institutions")
def list_institutions():
    """List all configured institutions with their staff counts."""
    from uraas.config.institutions import get_registry

    registry = get_registry()
    results = []
    for inst in registry.list_all():
        results.append(
            {
                "name": inst.name,
                "short_name": inst.short_name,
                "ror": inst.ror,
                "sub_region": inst.sub_region,
                "staff_count": len(inst.staff_names),
            }
        )
    return jsonify(results)


@app.route("/api/analytics/authors-search")
def authors_search():
    q = request.args.get("q", "")
    limit = clamped_int("limit", 10, 1, 100)
    institution = request.args.get("institution")
    session = SessionLocal()
    try:
        inst_name = (
            analytics._resolve_institution_name(institution) if institution else None
        )
        query = (
            session.query(Author.name, func.count(Item.id))
            .join(Author.items)
            .filter(Author.name.ilike(f"%{q}%"))
        )
        if inst_name:
            query = query.filter(Item.institution.ilike(f"%{inst_name}%"))
        authors = (
            query.group_by(Author.name)
            .order_by(desc(func.count(Item.id)))
            .limit(limit)
            .all()
        )
        return jsonify([{"name": a[0], "papers": a[1]} for a in authors])
    finally:
        session.close()


@app.route("/api/analytics/author-network")
def author_network():
    author_name = request.args.get("author", "").strip()
    return jsonify(analytics.get_author_network(author_name=author_name or None))


@app.route("/api/analytics/keyword-cloud")
def keyword_cloud():
    institution = request.args.get("institution", None)
    top_n = clamped_int("top_n", 60, 1, 150)
    return jsonify(analytics.get_keyword_cloud(top_n=top_n, institution=institution))


@app.route("/api/analytics/institution-leaderboard")
def institution_leaderboard():
    return jsonify(analytics.get_institution_leaderboard())


@app.route("/api/analytics/cache-flush", methods=["POST"])
def flush_analytics_cache():
    """Manual cache flush endpoint (admin use)."""
    analytics_cache.invalidate_all()
    return jsonify({"status": "success", "message": "Analytics cache flushed"})


@app.route("/api/analytics/faculty-comparison")
def faculty_comparison():
    faculties = request.args.getlist("faculty")
    institution = request.args.get("institution", None)
    session = SessionLocal()
    try:
        result = {}
        # If no specific faculties given, return all
        if not faculties:
            q = session.query(Community)
            if institution:
                q = q.filter(Community.institution.ilike(f"%{institution}%"))
            comms = q.all()
        else:
            comms = []
            for fac_name in faculties:
                comm = (
                    session.query(Community)
                    .filter(Community.name.ilike(f"%{fac_name}%"))
                    .first()
                )
                if comm:
                    comms.append(comm)

        for comm in comms:
            # Skip vague community names that are actually institution names
            if comm.name and len(comm.name) < 5:
                continue
            items = (
                session.query(Item)
                .join(Item.collections)
                .join(Collection.community)
                .filter(Community.id == comm.id)
                .options(selectinload(Item.authors))
                .all()
            )
            if not items:
                continue
            oa_count = sum(1 for i in items if "openAccess" in (i.dc_rights or ""))
            years = [i.publication_date.year for i in items if i.publication_date]
            authors_set = set(a.name for i in items for a in i.authors)
            # Top 3 keywords across all papers
            from collections import Counter

            kw_counter = Counter()
            for i in items:
                for kw in (i.ai_keywords or "").split(","):
                    kw = kw.strip()
                    if len(kw) > 3:
                        kw_counter[kw] += 1
            top_keywords = [k for k, _ in kw_counter.most_common(5)]
            result[comm.name] = {
                "total_papers": len(items),
                "open_access": oa_count,
                "restricted": len(items) - oa_count,
                "oa_rate": round(oa_count / len(items) * 100, 1) if items else 0,
                "unique_authors": len(authors_set),
                "year_range": [min(years), max(years)] if years else [],
                "peak_year": max(set(years), key=years.count) if years else None,
                "departments": len(comm.collections),
                "top_keywords": top_keywords,
                "institution": comm.institution or "Unknown",
            }
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/analytics/department-comparison")
def department_comparison():
    faculty = request.args.get("faculty", "")
    session = SessionLocal()
    try:
        comm = (
            session.query(Community)
            .filter(Community.name.ilike(f"%{faculty}%"))
            .first()
        )
        if not comm:
            return jsonify({})
        result = {}
        for coll in comm.collections:
            items = (
                session.query(Item)
                .join(Item.collections)
                .filter(Collection.id == coll.id)
                .options(selectinload(Item.authors))
                .all()
            )
            if not items:
                continue
            oa = sum(1 for i in items if "openAccess" in (i.dc_rights or ""))
            years = [i.publication_date.year for i in items if i.publication_date]
            result[coll.name] = {
                "total": len(items),
                "open_access": oa,
                "restricted": len(items) - oa,
                "oa_rate": round(oa / len(items) * 100, 1) if items else 0,
                "unique_authors": len(set(a.name for i in items for a in i.authors)),
                "years": sorted(set(years)),
            }
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/analytics/lecturer-profile")
def lecturer_profile():
    name = request.args.get("name", "").strip()
    session = SessionLocal()
    try:
        author = session.query(Author).filter(Author.name.ilike(f"%{name}%")).first()
        if not author:
            return jsonify({"error": "Author not found"}), 404
        # Eager-load the relationships walked below (collections→community, authors)
        # so the profile renders in a handful of queries instead of one-per-paper.
        items = (
            session.query(Item)
            .filter(Item.authors.any(Author.id == author.id))
            .options(
                selectinload(Item.authors),
                selectinload(Item.collections).selectinload(Collection.community),
            )
            .all()
        )
        oa = sum(1 for i in items if "openAccess" in (i.dc_rights or ""))
        years = sorted(
            set(i.publication_date.year for i in items if i.publication_date)
        )
        faculties = list(
            set(c.community.name for i in items for c in i.collections if c.community)
        )
        depts = list(set(c.name for i in items for c in i.collections))
        co_authors = {}
        for item in items:
            for a in item.authors:
                if a.name != author.name:
                    co_authors[a.name] = co_authors.get(a.name, 0) + 1
        top_co = sorted(co_authors.items(), key=lambda x: -x[1])[:10]
        return jsonify(
            {
                "name": author.name,
                "total_papers": len(items),
                "open_access": oa,
                "oa_rate": round(oa / len(items) * 100, 1) if items else 0,
                "active_years": years,
                "faculties": faculties,
                "departments": depts,
                "top_collaborators": [{"name": n, "papers": c} for n, c in top_co],
                "papers": [
                    {
                        "id": i.id,
                        "title": i.title,
                        "doi": i.doi,
                        "year": i.publication_date.year if i.publication_date else None,
                        "is_oa": "openAccess" in (i.dc_rights or ""),
                    }
                    for i in sorted(
                        items,
                        key=lambda x: x.publication_date
                        or __import__("datetime").datetime.min,
                        reverse=True,
                    )[:20]
                ],
            }
        )
    finally:
        session.close()


@app.route("/api/analytics/language-research")
def language_research():
    """Phase 7 cleanup: Uses pre-compiled regex from uraas.config.language_research."""
    from uraas.analytics.engine import STOP_WORDS
    from uraas.config.language_research import LANG_TIER1, LANG_TIER2, score_item

    session = SessionLocal()
    try:
        institution = request.args.get("institution", "").strip()
        q = session.query(Item)
        if institution:
            q = q.filter(Item.institution.ilike(f"%{institution}%"))
        items = q.all()

        matches = []
        keyword_counts: dict = {}
        for item in items:
            try:
                score, matched = score_item(item.title or "", item.abstract or "")
                if not score:
                    continue
                text = (f"{item.title or ''} {item.abstract or ''}").lower()
                import re as _re
                for word in _re.findall(r"\b[a-z]{5,}\b", text):
                    if word not in STOP_WORDS:
                        keyword_counts[word] = keyword_counts.get(word, 0) + 1
                matches.append(
                    {
                        "id": item.id,
                        "title": item.title,
                        "year": (
                            item.publication_date.year if item.publication_date else None
                        ),
                        "authors": [a.name for a in item.authors[:4]],
                        "is_oa": "openAccess" in (item.dc_rights or ""),
                        "score": score,
                        "matched_terms": matched[:6],
                    }
                )
            except Exception as e:
                logger.error("language_research item %s: %s", item.id, e)
                continue

        matches.sort(key=lambda x: (-x["score"], -(x.get("year") or 0)))
        top_keywords = sorted(keyword_counts.items(), key=lambda x: -x[1])[:20]
        return jsonify(
            {
                "total_language_papers": len(matches),
                "top_keywords": [{"keyword": k, "count": v} for k, v in top_keywords],
                "papers": matches[:50],
            }
        )
    except Exception as e:
        logger.error("language_research: %s", e)
        return (
            jsonify(
                {
                    "error": "Internal server error",
                    "total_language_papers": 0,
                    "top_keywords": [],
                    "papers": [],
                }
            ),
            500,
        )
    finally:
        session.close()




#  Multi-Institution Comparator (APA Core Feature)


@app.route("/api/comparator/compare", methods=["POST"])
def compare_institutions():
    """
    Compare multiple institutions across all metrics.
    Request body: {"ror_ids": ["ror1", "ror2", "ror3"]}
    """
    try:
        from uraas.services.comparator_engine import ComparatorEngine

        data = request.get_json()
        ror_ids = data.get("ror_ids", [])

        if not ror_ids or len(ror_ids) < 2:
            return jsonify({"error": "Provide at least 2 ROR IDs"}), 400

        if len(ror_ids) > 15:
            return jsonify({"error": "Maximum 15 institutions"}), 400

        comparison = ComparatorEngine.compare_institutions(ror_ids)
        return jsonify(comparison)

    except Exception as e:
        logger.error(f"compare_institutions: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/comparator/collaboration-mesh", methods=["POST"])
def collaboration_mesh():
    """
    Get collaboration network data for geographic visualization.
    Request body: {"ror_ids": ["ror1", "ror2", "ror3"]}
    """
    try:
        from uraas.services.comparator_engine import ComparatorEngine

        data = request.get_json()
        ror_ids = data.get("ror_ids", [])

        if not ror_ids:
            return jsonify({"error": "Provide ROR IDs"}), 400

        mesh = ComparatorEngine.get_collaboration_matrix(ror_ids)
        return jsonify(mesh)

    except Exception as e:
        logger.error(f"collaboration_mesh: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/comparator/senate-report", methods=["POST"])
def generate_senate_report():
    """
    Generate comprehensive senate report.
    Request body: {"ror_ids": ["ror1", "ror2"], "format": "json"}
    """
    try:
        from uraas.services.comparator_engine import ComparatorEngine

        data = request.get_json()
        ror_ids = data.get("ror_ids", [])
        format_type = data.get("format", "json")

        if not ror_ids:
            return jsonify({"error": "Provide ROR IDs"}), 400

        report = ComparatorEngine.generate_senate_report(ror_ids, format_type)

        if format_type == "json":
            return jsonify(report)
        elif format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "Institution",
                    "ROR",
                    "SC Papers",
                    "SC Authors",
                    "OA Rate %",
                    "Indigenous Knowledge",
                    "African Literature",
                    "Papers/Author",
                ]
            )
            for inst in report["detailed_comparison"]["institutions"]:
                m = inst["metrics"]
                writer.writerow(
                    [
                        inst["name"],
                        inst["ror_id"],
                        m.get("total_papers", 0),
                        m.get("total_authors", 0),
                        m.get("oa_rate", 0),
                        m.get("indigenous_knowledge", 0),
                        m.get("african_literature", 0),
                        m.get("papers_per_author", 0),
                    ]
                )
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=senate_report.csv"
                },
            )
        elif format_type == "pdf":
            # Plain-text report (PDF rendering would need reportlab; keep deps minimal)
            lines = [
                report["title"],
                "=" * len(report["title"]),
                f"Generated: {report['generated_at']}",
                f"Institutions: {report['institutions_analyzed']}",
                "",
                "Executive Summary:",
            ]
            for k, v in report["executive_summary"].items():
                lines.append(f"  {k}: {v}")
            lines += ["", "Recommendations:"]
            for r in report.get("recommendations", []):
                lines.append(f"  - {r}")
            return Response(
                "\n".join(lines),
                mimetype="text/plain",
                headers={
                    "Content-Disposition": "attachment; filename=senate_report.txt"
                },
            )
        else:
            return jsonify({"error": "Invalid format"}), 400

    except Exception as e:
        logger.error(f"generate_senate_report: {e}")
        return jsonify({"error": str(e)}), 500


#  Citation Tracking & Bibliometrics


@app.route("/api/citations/<int:item_id>")
def get_citations(item_id):
    """Get citation data for a paper — enriched with ARK + Pan-African share (Phase 5)."""
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(id=item_id).first()
        # Base citation count from DB (fast, no API call)
        base = {
            "item_id": item_id,
            "citation_count": item.cited_by_count or 0 if item else 0,
            "ark": item.ark or "" if item else "",
            "docid": item.docid or "" if item else "",
            "african_citation_share": item.african_citation_share if item else None,
            "openalex_id": item.openalex_id or "" if item else "",
        }
    except Exception:
        base = {"item_id": item_id, "citation_count": 0}
    finally:
        session.close()

    # Supplement with live CitationMetrics record if available
    try:
        from uraas.services.citation_tracker import get_paper_citations
        live = get_paper_citations(item_id)
        base.update(live)
    except Exception as e:
        logger.debug(f"get_citations live lookup {item_id}: {e}")
    return jsonify(base)


@app.route("/api/citations/velocity/export.csv")
def citations_velocity_csv():
    """Phase 4 — Streaming CSV export of the citation velocity time-series.

    Columns: year, citations_received, pan_african_share_pct, items_covered
    Query param: ?institution=<short_name>
    """
    try:
        institution = request.args.get("institution", "").strip().lower() or None
        data = analytics.get_citation_velocity(institution)
        series = data.get("by_year", [])
        share = data.get("pan_african_share_pct")
        covered = data.get("pan_african_share_items", 0)

        def gen():
            yield [
                "Year",
                "Citations Received",
                "Pan-African Share %",
                "Items Covered (pan-African)",
            ]
            for row in series:
                yield [
                    row["year"],
                    row["citations"],
                    share if share is not None else "",
                    covered,
                ]

        return csv_response(gen(), "citation_velocity.csv")
    except Exception as e:
        logger.error(f"citations_velocity_csv: {e}")
        return api_error(str(e))


@app.route("/api/citations/update/<int:item_id>", methods=["POST"])
def update_citations(item_id):
    """Manually trigger citation update for a paper."""
    try:
        from uraas.services.citation_tracker import CitationTracker

        success = CitationTracker.update_paper_citations(item_id)
        return jsonify({"success": success, "item_id": item_id})
    except Exception as e:
        logger.error(f"update_citations {item_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/author/<int:author_id>/metrics")
def get_author_metrics(author_id):
    """Get bibliometric indicators for an author (h-index, citations, etc.)."""
    try:
        from uraas.services.citation_tracker import get_author_bibliometrics

        return jsonify(get_author_bibliometrics(author_id))
    except Exception as e:
        logger.error(f"get_author_metrics {author_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/citations/bulk-update", methods=["POST"])
def bulk_update_citations():
    """Bulk update citations for papers (admin endpoint)."""
    try:
        from uraas.services.citation_tracker import CitationTracker

        limit = clamped_int("limit", 50, 1, 200)
        force = request.args.get("force", "false").lower() == "true"
        stats = CitationTracker.bulk_update_citations(limit=limit, force=force)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"bulk_update_citations: {e}")
        return jsonify({"error": str(e)}), 500


#  Advanced Search


@app.route("/api/search/advanced")
def advanced_search():
    """
    Advanced search with Boolean operators and field-specific queries.

    Query examples:
        ?q="machine learning" AND author:smith
        ?q=(covid OR pandemic) AND year:2020
        ?q=title:cancer NOT lung
        ?q=author:okonkwo AND faculty:science

    Supported fields:
        title, abstract, author, year, doi, faculty, department, keyword, language, oa

    Operators:
        AND, OR, NOT, parentheses for grouping, "quotes" for phrases
    """
    try:
        from uraas.services.advanced_search import SearchQuery

        query = request.args.get("q", "").strip()
        limit = clamped_int("limit", 50, 1, 200)
        offset = clamped_int("offset", 0, 0, 100000)
        sort_by = request.args.get(
            "sort", "relevance"
        )  # relevance, date, citations, title

        filters = {
            "year_from": request.args.get("year_from", type=int),
            "year_to": request.args.get("year_to", type=int),
            "oa_only": request.args.get("oa_only", "false").lower() == "true",
            "faculty": request.args.get("faculty"),
            "has_pdf": request.args.get("has_pdf", "false").lower() == "true",
        }

        results = SearchQuery.execute_search(
            query=query, limit=limit, offset=offset, sort_by=sort_by, filters=filters
        )

        return jsonify(results)

    except Exception as e:
        logger.error(f"advanced_search: {e}")
        return jsonify({"error": str(e), "total": 0, "results": []}), 500


@app.route("/api/search/suggest")
def search_suggestions():
    """Get autocomplete suggestions for search queries."""
    try:
        from uraas.services.advanced_search import SearchQuery

        partial = request.args.get("q", "").strip()
        field = request.args.get("field", "all")

        suggestions = SearchQuery.get_search_suggestions(partial, field)
        return jsonify({"suggestions": suggestions})

    except Exception as e:
        logger.error(f"search_suggestions: {e}")
        return jsonify({"suggestions": []}), 500


#  APA Novel Metrics


@app.route("/api/analytics/tk-vitality-score")
def tk_vitality_score():
    institution = request.args.get("institution", None)
    return jsonify(analytics.get_tk_vitality_score(institution=institution))


@app.route("/api/analytics/linguistic-diversity-index")
def linguistic_diversity_index():
    return jsonify(analytics.get_linguistic_diversity_index())


@app.route("/api/analytics/special-collections")
def special_collections():
    institution = request.args.get("institution", None)
    return jsonify(analytics.get_special_collections_metrics(institution=institution))


@app.route("/api/analytics/special-collections/overview")
def special_collections_overview():
    institution = request.args.get("institution", None)
    return jsonify(analytics.get_special_collections_overview(institution=institution))


@app.route("/api/analytics/special-collections/export.csv")
def export_special_collections_csv():
    """Download special collections data as CSV."""
    try:
        rows = analytics.get_special_collections_csv_data()
        output = io.StringIO()
        writer = csv.writer(output)
        for row in rows:
            writer.writerow(row)
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=uraas_special_collections.csv"
            },
        )
    except Exception as e:
        logger.error(f"export_special_collections_csv: {e}")
        return jsonify({"error": str(e)}), 500


# ── Framework Alignment endpoints (AU charters / Agenda 2063 / blocs) ────────
# Scores are precomputed at ingest / by scripts/backfill_alignment.py and read
# from alignment_aggregates — these endpoints never score at request time.


def _resolve_inst_name():
    institution = request.args.get("institution", "").strip().lower()
    return analytics._resolve_institution_name(institution) if institution else None


def _alignment_top_papers(session, top_item_ids, framework, pillar):
    """Evidence chips: resolve top item ids to titles + matched keywords."""
    from uraas.services.alignment_engine import get_alignment

    ids = [int(i) for i in (top_item_ids or "").split(",") if i]
    papers = []
    for item in session.query(Item).filter(Item.id.in_(ids)).all():
        pdata = (
            get_alignment(item).get(framework, {}).get("pillars", {}).get(pillar, {})
        )
        papers.append(
            {
                "id": item.id,
                "title": item.title or "Untitled",
                "score": pdata.get("score", 0),
                "matched_keywords": pdata.get("matched_keywords", [])[:4],
            }
        )
    papers.sort(key=lambda p: -p["score"])
    return papers


@app.route("/api/alignment/frameworks")
def alignment_frameworks():
    """All frameworks + pillar metadata for the selector UI."""
    from uraas.config.alignment_frameworks import FRAMEWORK_GROUPS, FRAMEWORKS
    from uraas.services.alignment_engine import scoring_mode

    frameworks = [
        {
            "key": fkey,
            "name": f["name"],
            "type": f["type"],
            "year": f.get("year"),
            "color": f.get("color", "#3b82f6"),
            "pillars": [
                {"key": pk, "name": p["name"], "description": p["description"]}
                for pk, p in f["pillars"].items()
            ],
        }
        for fkey, f in FRAMEWORKS.items()
    ]
    return api_ok(
        {"frameworks": frameworks, "groups": FRAMEWORK_GROUPS, "mode": scoring_mode()}
    )


@app.route("/api/alignment/profile")
def alignment_profile():
    """Radar-chart profile for one framework: per-pillar avg score + evidence."""
    from uraas.config.alignment_frameworks import FRAMEWORKS, GAP_THRESHOLD
    from uraas.database import AlignmentAggregate
    from uraas.services.narratives import narrate

    framework = request.args.get("framework", "agenda2063")
    if framework not in FRAMEWORKS:
        return api_error(f"Unknown framework: {framework}", 400)
    inst_name = _resolve_inst_name()

    cache_key = f"align_profile_{framework}_{inst_name or 'all'}"
    cached = analytics_cache.get(cache_key)
    if cached:
        return jsonify(cached)

    session = SessionLocal()
    try:
        fdef = FRAMEWORKS[framework]
        rows = {
            r.pillar: r
            for r in session.query(AlignmentAggregate)
            .filter_by(institution=inst_name or "", framework=framework)
            .all()
        }
        pillars = []
        for pkey, pdef in fdef["pillars"].items():
            r = rows.get(pkey)
            avg = r.avg_score if r else 0.0
            pillars.append(
                {
                    "key": pkey,
                    "name": pdef["name"],
                    "avg_score": avg,
                    "paper_count": r.paper_count if r else 0,
                    "is_gap": avg < GAP_THRESHOLD,
                    "top_papers": (
                        _alignment_top_papers(session, r.top_item_ids, framework, pkey)
                        if r
                        else []
                    ),
                }
            )

        scores = [p["avg_score"] for p in pillars]
        top = max(pillars, key=lambda p: p["avg_score"]) if pillars else None
        data = {
            "framework": framework,
            "framework_name": fdef["name"],
            "color": fdef.get("color", "#3b82f6"),
            "institution": inst_name or "All Institutions",
            "pillars": pillars,
            "overall_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "gap_threshold": GAP_THRESHOLD,
        }
        narrative = (
            narrate(
                "alignment_profile",
                institution=inst_name or "The repository",
                top_pillar=top["name"],
                top_score=top["avg_score"],
                top_count=top["paper_count"],
                gap_count=sum(1 for p in pillars if p["is_gap"]),
                pillar_count=len(pillars),
                threshold=GAP_THRESHOLD,
            )
            if top
            else ""
        )
        resp = api_ok(data, narrative=narrative, methodology_key="alignment_score")
        analytics_cache.set(cache_key, resp.get_json(), ttl=1800)
        return resp
    except Exception as e:
        logger.error(f"alignment_profile: {e}")
        return api_error(str(e))
    finally:
        session.close()


@app.route("/api/alignment/matrix")
def alignment_matrix():
    """Heatmap cells: every (framework, pillar) avg score for one institution."""
    from uraas.config.alignment_frameworks import FRAMEWORKS
    from uraas.database import AlignmentAggregate

    inst_name = _resolve_inst_name()
    cache_key = f"align_matrix_{inst_name or 'all'}"
    cached = analytics_cache.get(cache_key)
    if cached:
        return jsonify(cached)

    session = SessionLocal()
    try:
        rows = (
            session.query(AlignmentAggregate)
            .filter_by(institution=inst_name or "")
            .all()
        )
        scored = {(r.framework, r.pillar): r for r in rows}
        cells = []
        for fkey, f in FRAMEWORKS.items():
            for pkey, pdef in f["pillars"].items():
                r = scored.get((fkey, pkey))
                cells.append(
                    {
                        "framework": fkey,
                        "framework_name": f["name"],
                        "pillar": pkey,
                        "pillar_name": pdef["name"],
                        "avg_score": r.avg_score if r else 0.0,
                        "paper_count": r.paper_count if r else 0,
                    }
                )
        data = {
            "institution": inst_name or "All Institutions",
            "frameworks": [
                {"key": k, "name": f["name"], "color": f.get("color")}
                for k, f in FRAMEWORKS.items()
            ],
            "cells": cells,
        }
        resp = api_ok(data, methodology_key="alignment_score")
        analytics_cache.set(cache_key, resp.get_json(), ttl=1800)
        return resp
    except Exception as e:
        logger.error(f"alignment_matrix: {e}")
        return api_error(str(e))
    finally:
        session.close()


@app.route("/api/alignment/gaps")
def alignment_gaps():
    """Research Gap Radar: pillars below threshold, ascending by score."""
    from uraas.config.alignment_frameworks import FRAMEWORKS, GAP_THRESHOLD
    from uraas.database import AlignmentAggregate
    from uraas.services.narratives import narrate

    inst_name = _resolve_inst_name()
    try:
        threshold = float(request.args.get("threshold", GAP_THRESHOLD))
    except ValueError:
        threshold = GAP_THRESHOLD

    session = SessionLocal()
    try:
        rows = {
            (r.framework, r.pillar): r
            for r in session.query(AlignmentAggregate)
            .filter_by(institution=inst_name or "")
            .all()
        }
        gaps = []
        for fkey, f in FRAMEWORKS.items():
            for pkey, pdef in f["pillars"].items():
                r = rows.get((fkey, pkey))
                avg = r.avg_score if r else 0.0
                if avg < threshold:
                    gaps.append(
                        {
                            "framework": fkey,
                            "framework_name": f["name"],
                            "pillar": pkey,
                            "pillar_name": pdef["name"],
                            "avg_score": avg,
                            "paper_count": r.paper_count if r else 0,
                        }
                    )
        gaps.sort(key=lambda g: g["avg_score"])
        worst = gaps[0] if gaps else None
        narrative = (
            narrate(
                "alignment_gaps",
                gap_count=len(gaps),
                framework_count=len({g["framework"] for g in gaps}),
                worst_pillar=worst["pillar_name"],
                worst_framework=worst["framework_name"],
                worst_score=worst["avg_score"],
            )
            if worst
            else ""
        )
        return api_ok(
            {
                "gaps": gaps,
                "threshold": threshold,
                "institution": inst_name or "All Institutions",
            },
            narrative=narrative,
            methodology_key="alignment_gap",
        )
    except Exception as e:
        logger.error(f"alignment_gaps: {e}")
        return api_error(str(e))
    finally:
        session.close()


@app.route("/api/alignment/export.csv")
def alignment_export_csv():
    """CSV of the full alignment matrix for the selected institution."""
    from uraas.config.alignment_frameworks import FRAMEWORKS
    from uraas.database import AlignmentAggregate

    inst_name = _resolve_inst_name()
    session = SessionLocal()
    try:
        rows = {
            (r.framework, r.pillar): r
            for r in session.query(AlignmentAggregate)
            .filter_by(institution=inst_name or "")
            .all()
        }

        def generate():
            yield ["Framework", "Pillar", "Avg Score (0-100)", "Aligned Papers"]
            for fkey, f in FRAMEWORKS.items():
                for pkey, pdef in f["pillars"].items():
                    r = rows.get((fkey, pkey))
                    yield [
                        f["name"],
                        pdef["name"],
                        r.avg_score if r else 0.0,
                        r.paper_count if r else 0,
                    ]

        return csv_response(generate(), "alignment_matrix.csv")
    except Exception as e:
        logger.error(f"alignment_export_csv: {e}")
        return api_error(str(e))
    finally:
        session.close()


# ── Intra-African collaboration endpoints ─────────────────────────────────────


@app.route("/api/collaboration/overview")
def collaboration_overview():
    """Intra-African Collaboration Index + benchmark context."""
    from uraas.services.narratives import narrate

    try:
        institution = request.args.get("institution", "").strip().lower() or None
        data = analytics.get_collaboration_overview(institution)
        partners = data.get("top_partner_countries", [])
        narrative = narrate(
            "intra_african" if partners else "intra_african_no_partner",
            pct=data.get("intra_african_pct", 0),
            ratio=data.get("ratio_vs_baseline", 0),
            baseline=data.get("baseline_pct", 8.4),
            top_partner=partners[0]["name"] if partners else "",
        )
        return api_ok(
            data,
            narrative=narrative,
            methodology_key="intra_african_collaboration",
        )
    except Exception as e:
        logger.error(f"collaboration_overview: {e}")
        return api_error(str(e))


@app.route("/api/collaboration/matrix")
def collaboration_matrix():
    """African country-pair co-publication matrix."""
    from uraas.services.narratives import narrate

    try:
        institution = request.args.get("institution", "").strip().lower() or None
        data = analytics.get_country_pair_matrix(institution)
        top = data["pairs"][0] if data["pairs"] else None
        narrative = (
            narrate(
                "country_pairs",
                pair_count=len(data["pairs"]),
                country_a=top["source_name"],
                country_b=top["target_name"],
                count=top["count"],
            )
            if top
            else ""
        )
        return api_ok(data, narrative=narrative, methodology_key="country_pair_matrix")
    except Exception as e:
        logger.error(f"collaboration_matrix: {e}")
        return api_error(str(e))


@app.route("/api/collaboration/countries")
def collaboration_countries():
    """Per-country paper counts for the Africa choropleth."""
    try:
        institution = request.args.get("institution", "").strip().lower() or None
        return api_ok(
            {"countries": analytics.get_country_aggregates(institution)},
            methodology_key="intra_african_collaboration",
        )
    except Exception as e:
        logger.error(f"collaboration_countries: {e}")
        return api_error(str(e))


@app.route("/api/collaboration/arcs")
def collaboration_arcs():
    """GeoJSON great-circle arcs for the collaboration map (bare GeoJSON)."""
    try:
        institution = request.args.get("institution", "").strip().lower() or None
        return jsonify(analytics.get_collaboration_arcs(institution))
    except Exception as e:
        logger.error(f"collaboration_arcs: {e}")
        return api_error(str(e))


@app.route("/api/collaboration/network")
def collaboration_network():
    """Author collaboration network with Louvain communities + centrality."""
    try:
        author = request.args.get("author", "").strip() or None
        limit = clamped_int("limit", 30, 1, 100)
        return api_ok(analytics.get_author_network(author, limit))
    except Exception as e:
        logger.error(f"collaboration_network: {e}")
        return api_error(str(e))


@app.route("/api/citations/velocity")
def citations_velocity():
    """Repository citation velocity + Pan-African citation share."""
    from uraas.services.narratives import narrate

    try:
        institution = request.args.get("institution", "").strip().lower() or None
        data = analytics.get_citation_velocity(institution)
        series = data.get("by_year", [])
        recent = series[-1]["citations"] if series else 0
        parts = []
        if series:
            parts.append(
                narrate(
                    "citation_velocity",
                    recent_rate=recent,
                    avg_first2y=data.get("avg_first2y", 0),
                )
            )
        if data.get("pan_african_share_pct") is not None:
            parts.append(
                narrate(
                    "pan_african_share",
                    share=data["pan_african_share_pct"],
                    covered=data.get("pan_african_share_items", 0),
                )
            )
        return api_ok(
            data,
            narrative=" ".join(p for p in parts if p),
            methodology_key="citation_velocity",
        )
    except Exception as e:
        logger.error(f"citations_velocity: {e}")
        return api_error(str(e))


@app.route("/api/collaboration/export.csv")
def collaboration_export_csv():
    """CSV export — ?view=matrix (default) or ?view=countries."""
    try:
        institution = request.args.get("institution", "").strip().lower() or None
        view = request.args.get("view", "matrix")
        if view == "countries":
            rows_data = analytics.get_country_aggregates(institution)

            def gen_countries():
                yield ["Country", "ISO2", "Papers", "Intra-African Papers"]
                for r in rows_data:
                    yield [r["name"], r["code"], r["papers"], r["intra_african"]]

            return csv_response(gen_countries(), "collaboration_countries.csv")

        matrix = analytics.get_country_pair_matrix(institution)

        def gen_matrix():
            yield ["Country A", "Country B", "Co-publications"]
            for p in matrix["pairs"]:
                yield [p["source_name"], p["target_name"], p["count"]]

        return csv_response(gen_matrix(), "collaboration_matrix.csv")
    except Exception as e:
        logger.error(f"collaboration_export_csv: {e}")
        return api_error(str(e))


@app.route("/api/analytics/staff-directory")
def staff_directory():
    """
    Returns real staff records with name, department, faculty, ORCID for each institution.
    Query params: ?institution=unilag (optional; returns all if omitted)
    """
    from uraas.config.institutions import get_registry

    registry = get_registry()
    institution_filter = request.args.get("institution", "").strip().lower()

    result = []
    insts = (
        [registry.get(institution_filter)]
        if institution_filter
        else registry.list_all()
    )
    insts = [i for i in insts if i]  # filter None

    for inst in insts:
        # Get dynamic authors from database
        dynamic_authors = analytics.get_top_authors(
            limit=5000, institution=inst.short_name
        )

        # Merge dynamic ORCIDs/RORs with static departments
        staff_data = []
        static_lookup = {r["name"].lower(): r for r in inst.staff_records}

        for author in dynamic_authors:
            a_name = author.get("author", "")
            static_rec = static_lookup.get(a_name.lower(), {})

            staff_data.append(
                {
                    "name": a_name,
                    "orcid": author.get("orcid") or static_rec.get("orcid"),
                    "ror": author.get("ror"),
                    "department": static_rec.get("department"),
                    "faculty": static_rec.get("faculty"),
                    "paper_count": author.get("count", 0),
                }
            )

        result.append(
            {
                "institution": inst.name,
                "short_name": inst.short_name,
                "country": inst.country,
                "staff": staff_data,
                "staff_count": len(staff_data),
                "staff_with_orcid": sum(1 for s in staff_data if s.get("orcid")),
                "departments": inst.departments,
            }
        )

    return jsonify(result)


#  Export


@app.route("/api/export/papers.csv")
def export_csv():
    """Streaming CSV of every paper (yield_per avoids loading all rows)."""
    from sqlalchemy.orm import selectinload

    def generate():
        session = SessionLocal()
        try:
            yield [
                "ID",
                "Title",
                "Authors",
                "DOI",
                "ARK",
                "DocID",
                "Year",
                "Faculty",
                "Open Access",
                "Source",
            ]
            # selectinload (not joinedload) is required with yield_per — joined
            # eager loads against collections need row-uniquing, which yield_per
            # forbids.
            q = (
                session.query(Item)
                .options(
                    selectinload(Item.authors),
                    selectinload(Item.collections).selectinload(Collection.community),
                )
                .order_by(desc(Item.created_at))
            )
            for i in q.yield_per(200):
                authors = "; ".join(a.name for a in i.authors)
                faculty = i.collections[0].community.name if i.collections else ""
                year = i.publication_date.year if i.publication_date else ""
                yield [
                    i.id,
                    i.title or "",
                    authors,
                    i.doi or "",
                    i.ark or "",
                    i.docid or "",
                    year,
                    faculty,
                    "Yes" if "openAccess" in (i.dc_rights or "") else "No",
                    i.source_repository or "",
                ]
        finally:
            session.close()

    return csv_response(generate(), "uraas_papers.csv")


@app.route("/api/export/papers.bibtex")
def export_bibtex():
    session = SessionLocal()
    try:
        items = session.query(Item).order_by(desc(Item.created_at)).all()
        entries = []
        for i in items:
            authors = [a.name for a in i.authors]
            first_last = authors[0].split()[-1] if authors else "Unknown"
            year = str(i.publication_date.year) if i.publication_date else "nd"
            key = __import__("re").sub(r"[^a-zA-Z0-9]", "", f"{first_last}{year}")
            author_str = " and ".join(authors) if authors else "Unknown"
            title = (i.title or "Untitled").replace("{", "").replace("}", "")
            doi_line = f"  doi = {{{i.doi}}},\n" if i.doi else ""
            url_line = f"  url = {{{i.url}}},\n" if i.url else ""
            institution = (i.institution or "").strip() or "Unknown"
            entries.append(
                f"@article{{{key},\n  title = {{{title}}},\n  author = {{{author_str}}},\n  year = {{{year}}},\n  institution = {{{institution}}},\n"
                + doi_line
                + url_line
                + "}"
            )
        return Response(
            "\n\n".join(entries),
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=uraas_papers.bib"},
        )
    finally:
        session.close()


#  Crawler control


@app.route("/api/crawler/start", methods=["POST"])
def start_crawler():
    global crawler_process
    with crawler_lock:
        if crawler_process and crawler_process.poll() is None:
            return (
                jsonify({"status": "error", "message": "Crawler already running"}),
                400,
            )
        data = request.get_json() or {}
        target = min(max(int(data.get("target", 20)), 1), 250)
        institution = data.get("institution", "unilag")
        # Validate institution against registry before passing to subprocess.
        if institution != "all":
            from uraas.config.institutions import get_registry as _get_reg
            _reg = _get_reg()
            if not _reg.get(institution):
                return jsonify({"status": "error", "message": f"Unknown institution: {institution}"}), 400
        # Default ON — heavy bias toward Special Collections in every crawl.
        boost_special = bool(data.get("boost_special", True))
        sc_only = bool(data.get("sc_only", False))
        # Optional spider selection (allowlisted). "oai" = read-only harvest of
        # the institution's own repository (theses/grey literature).
        spider = data.get("spider", "openalex")
        if spider not in ("openalex", "crossref", "arxiv", "orcid", "oai"):
            return jsonify({"status": "error", "message": f"Unknown spider: {spider}"}), 400
        # OAI date window — accept only a safe YYYY-MM-DD shape; ignore anything else.
        _date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        from_date = data.get("from_date")
        until_date = data.get("until_date")
        from_date = from_date if (from_date and _date_re.match(str(from_date))) else None
        until_date = until_date if (until_date and _date_re.match(str(until_date))) else None
        try:
            # Derive project root and script path
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            script_path = os.path.join(
                project_root, "scripts", "crawl_multi_institution.py"
            )

            cmd = [__import__("sys").executable, script_path, "--target", str(target)]
            if institution != "all":
                cmd.extend(["--institutions", institution])
            cmd.extend(["--spider", spider])
            if spider == "oai":
                if from_date:
                    cmd.extend(["--from-date", from_date])
                if until_date:
                    cmd.extend(["--until-date", until_date])
            else:
                if not boost_special:
                    cmd.append("--no-boost-special")
                if sc_only:
                    cmd.append("--sc-only")

            logger.info(f"Executing crawler command: {' '.join(cmd)}")

            # Pass PYTHONUNBUFFERED so terminal output appears in real-time order
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
            )
            crawler_process = process
            thread = threading.Thread(
                target=crawler_monitor, args=(process,), daemon=True
            )
            thread.start()
            return jsonify(
                {
                    "status": "success",
                    "message": f"Crawler started  target {target} papers",
                }
            )
        except FileNotFoundError:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Crawler script not found at {script_path}",
                    }
                ),
                500,
            )
        except Exception as e:
            logger.error("start_crawler: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/crawler/stop", methods=["POST"])
def stop_crawler():
    global crawler_process
    with crawler_lock:
        if crawler_process and crawler_process.poll() is None:
            crawler_process.terminate()
            crawler_process = None
            return jsonify({"status": "success", "message": "Crawler stopped"})
        return jsonify({"status": "warning", "message": "No crawler running"})


@app.route("/api/crawler/status")
def crawler_status():
    with crawler_lock:
        running = crawler_process is not None and crawler_process.poll() is None
    return jsonify({"status": "running" if running else "idle"})


#  Health Check Endpoint for Render


@app.route("/health")
def health_check():
    """Render readiness probe (Phase 8 enhanced).

    Checks: DB connectivity + latency, disk space, analytics cache, methodology.
    Returns 200 if all checks pass, 503 if any critical check fails.
    """
    import time
    from datetime import datetime

    from sqlalchemy import text
    from uraas.config.methodology import METHODOLOGY

    t_start = time.monotonic()
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": os.getenv("RENDER_GIT_COMMIT", "dev")[:8],
        "checks": {},
    }

    # DB check (with latency)
    t0 = time.monotonic()
    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        session.close()
        health_status["checks"]["database"] = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as e:
        health_status["checks"]["database"] = {"status": f"error: {str(e)}"}
        health_status["status"] = "unhealthy"
        logger.error(f"Database health check failed: {str(e)}")

    # Analytics cache probe
    try:
        analytics_cache.get("__health__")
        health_status["checks"]["cache"] = {"status": "ok"}
    except Exception as e:
        health_status["checks"]["cache"] = {"status": f"error: {str(e)}"}

    # Methodology sanity
    health_status["checks"]["methodology"] = {
        "status": "ok",
        "metric_count": len(METHODOLOGY),
    }

    # Disk space check on persistent volume
    try:
        storage_path = config.STORAGE_PATH
        if os.path.exists(storage_path):
            import shutil
            stat = shutil.disk_usage(storage_path)
            free_gb = stat.free / (1024**3)
            health_status["checks"]["disk_space_gb"] = round(free_gb, 2)
            if free_gb < 1:
                health_status["status"] = "unhealthy"
                health_status["checks"]["disk_space"] = "critical"
        else:
            health_status["checks"]["disk_space"] = "storage path not found"
    except Exception as e:
        health_status["checks"]["disk_space"] = f"error: {str(e)}"

    health_status["response_ms"] = round((time.monotonic() - t_start) * 1000, 1)
    status_code = 200 if health_status["status"] == "healthy" else 503
    return jsonify(health_status), status_code


@app.route("/api/university-registry", methods=["GET"])
def get_university_registry():
    """
    Get the comprehensive 52-country African university registry.
    """
    try:
        import json

        registry_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "university_registry.json",
        )
        if not os.path.exists(registry_path):
            registry_path = "data/university_registry.json"

        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        logger.error(f"get_university_registry: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports/unilag-subregion", methods=["GET"])
def get_unilag_report():
    """
    Generate draft report of UNILAG contributions to African languages in West Africa.
    """
    session = SessionLocal()
    try:
        import json
        from datetime import datetime

        from uraas.utils.ai_classifier import AU_CHARTER_TARGETS, classify_au_targets

        # UNILAG ROR
        unilag_ror = "https://ror.org/05rk03822"

        # 1. Fetch UNILAG items
        unilag_items = session.query(Item).filter(Item.ror == unilag_ror).all()
        total_unilag = len(unilag_items)

        # 2. Fetch West Africa items (excluding UNILAG, e.g. UI and Covenant)
        west_africa_rors = [
            "https://ror.org/01js2sh04",
            "https://ror.org/0545s4788",
        ]  # UI and Covenant
        wa_items = session.query(Item).filter(Item.ror.in_(west_africa_rors)).all()
        total_wa = len(wa_items)

        # 3. Analyze UNILAG papers against AU Charter Target 2 (African Languages)
        target2_compliant = 0
        keywords_found = set()
        by_year = {}

        for item in unilag_items:
            results = classify_au_targets(
                item.title or "", item.abstract or "", item.dc_subject or ""
            )
            for r in results:
                if r["target_number"] == 2:
                    target2_compliant += 1
                    keywords_found.update(r["matched_keywords"])
                    year = item.publication_date.year if item.publication_date else None
                    if year:
                        by_year[year] = by_year.get(year, 0) + 1

        # Determine gaps
        all_t2_keywords = AU_CHARTER_TARGETS[2]["keywords"]
        keywords_gap = [kw for kw in all_t2_keywords if kw not in keywords_found]

        # 4. Compare with West African average
        wa_target2_compliant = 0
        for item in wa_items:
            results = classify_au_targets(
                item.title or "", item.abstract or "", item.dc_subject or ""
            )
            for r in results:
                if r["target_number"] == 2:
                    wa_target2_compliant += 1

        unilag_compliance_rate = (
            round(target2_compliant / total_unilag * 100, 1) if total_unilag else 0.0
        )
        wa_compliance_rate = (
            round(wa_target2_compliant / total_wa * 100, 1) if total_wa else 0.0
        )

        report_data = {
            "title": "Decolonizing Knowledge: UNILAG Contributions to African Languages & Cultural Renaissance in West Africa",
            "metadata": {
                "institution": "University of Lagos (UNILAG)",
                "subregion": "West Africa",
                "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "introduction": (
                "This report evaluates the academic contributions of the University of Lagos (UNILAG) "
                "toward the development of African languages and the decolonization of science in the West African sub-region. "
                "Aligned with the African Union Charter for African Cultural Renaissance, specifically Target 2 (Development of African Languages), "
                "this analysis highlights the intersection of linguistic preservation, local knowledge systems, and active "
                "institutional engagement in decolonial research."
            ),
            "statistics": {
                "total_curated": total_unilag,
                "compliant_count": target2_compliant,
                "compliance_rate": unilag_compliance_rate,
                "gaps_count": total_unilag - target2_compliant,
                "keywords_found": list(keywords_found),
                "keywords_gap": keywords_gap,
            },
            "scores_and_trends": {
                "timeline": [
                    {"year": y, "count": by_year[y]} for y in sorted(by_year.keys())
                ],
                "comparison": {
                    "unilag_rate": unilag_compliance_rate,
                    "west_africa_rate": wa_compliance_rate,
                    "unilag_compliant": target2_compliant,
                    "west_africa_compliant": wa_target2_compliant,
                },
            },
            "conclusion": (
                f"UNILAG shows solid alignment with the African Union Charter targets, with a decolonial compliance rate of {unilag_compliance_rate}%. "
                f"Linguistic preservation is robust, particularly with keywords like '{', '.join(list(keywords_found)[:4])}' being highly active. "
                f"However, critical gaps remain in the development of scientific literature in local languages. "
                f"To bridge this gap, future research should focus on areas like '{', '.join(keywords_gap[:4])}' to ensure a more comprehensive "
                "contribution to the African Union's Renaissance targets."
            ),
        }
        return jsonify(report_data)
    except Exception as e:
        logger.error(f"get_unilag_report: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


#  Error Handlers


@app.errorhandler(404)
def not_found_error(error):
    """Custom 404 error handler."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Resource not found"}), 404
    return render_template("index.html"), 404  # SPA fallback


@app.errorhandler(500)
def internal_error(error):
    """Custom 500 error handler."""
    logger.error(f"Internal server error: {str(error)}")
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return jsonify({"error": "Internal server error"}), 500


# Phase 8: /api/version endpoint


@app.route("/api/version")
def api_version():
    """Version manifest — commit hash + phase badges for the dashboard UI."""
    return jsonify(
        {
            "version": os.getenv("RENDER_GIT_COMMIT", "dev")[:8],
            "env": "production" if config.is_production() else "development",
            "phases_completed": [
                "P4_citation_velocity",
                "P5_ark_pids",
                "P6_credibility",
                "P7_cleanup",
                "P8_render_prep",
            ],
        }
    )



#  Run

if __name__ == "__main__":
    # Apply production configuration if on Render
    from uraas.production_config import ProductionConfig

    ProductionConfig.apply_config(app)

    # Get port from environment (Render provides this)
    port = int(os.getenv("PORT", config.DASHBOARD_PORT))

    # Determine if running in production
    is_production = ProductionConfig.is_production()

    if is_production:
        logger.info("=" * 70)
        logger.info("URAAS Dashboard Starting (Production Mode)")
        logger.info("=" * 70)
        logger.info(f"Port: {port}")
        logger.info(f"Database: {os.getenv('DATABASE_URL', 'Not configured')[:50]}...")
        logger.info(f"Storage: {config.STORAGE_PATH}")
        logger.info(f"Health check: http://0.0.0.0:{port}/health")
        logger.info("=" * 70)
    else:
        logger.info("=" * 70)
        logger.info("URAAS Dashboard Starting (Development Mode)")
        logger.info("=" * 70)
        logger.info(f"Dashboard URL: http://localhost:{port}")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 70)

    # Run with SocketIO
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=not is_production,
        use_reloader=not is_production,
    )
