import csv
import io
import logging
import os
import re
import subprocess
import threading

from flask import Flask, Response, jsonify, render_template, request, send_file
from flask_socketio import SocketIO
from sqlalchemy import desc, extract, func, or_

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
from uraas.utils.analytics_cache import analytics_cache
from uraas.utils.docid_generator import docid_generator

app = Flask(__name__)
app.config["SECRET_KEY"] = config.DASHBOARD_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")
logger = logging.getLogger(__name__)
crawler_process = None
crawler_lock = threading.Lock()
docid_crawler_process = None
docid_crawler_lock = threading.Lock()


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


def docid_crawler_monitor(process):
    global docid_crawler_process
    try:
        for line in iter(process.stdout.readline, b""):
            with docid_crawler_lock:
                if docid_crawler_process is None or docid_crawler_process != process:
                    break
            line_decoded = line.decode("utf-8", errors="replace").strip()
            if not line_decoded:
                continue
            socketio.emit("docid_terminal_output", {"line": line_decoded})
            if "[OK]" in line_decoded:
                socketio.emit("docid_crawl_status", {"status": "running"})
                try:
                    title = line_decoded.split("] ", 1)[-1].strip()
                    socketio.emit("docid_crawl_progress", {"title": title})
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()
        with docid_crawler_lock:
            if docid_crawler_process == process:
                docid_crawler_process = None
        socketio.emit("docid_crawl_status", {"status": "stopped"})


@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/api/papers/<int:item_id>/download")
def download_paper(item_id):
    session = SessionLocal()
    try:
        file_record = session.query(File).filter_by(item_id=item_id).first()
        if not file_record:
            return jsonify({"error": "PDF not found"}), 404
        file_path = file_record.file_path
        if not os.path.isabs(file_path):
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            file_path = os.path.normpath(os.path.join(project_root, file_path))
        if not os.path.exists(file_path):
            return jsonify({"error": "PDF file missing from storage"}), 404
        item = session.query(Item).filter_by(id=item_id).first()
        filename = (
            f"{item.title[:50]}.pdf" if item and item.title else f"paper_{item_id}.pdf"
        )
        filename = "".join(
            c for c in filename if c.isalnum() or c in (" ", "-", "_", ".")
        ).strip()
        return send_file(
            file_path,
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
        institution = (item.institution or "").strip() or "Unknown"
        bibtex = (
            f"@article{{{key},\n  title = {{{title}}},\n  author = {{{author_str}}},\n  year = {{{year}}},\n  institution = {{{institution}}},\n"
            + doi_line
            + url_line
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
        sc_ids = analytics._get_sc_item_ids(session, institution)
        if not sc_ids:
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

        q_item = session.query(Item).filter(Item.id.in_(sc_ids))
        q_author = session.query(Author).join(Author.items).filter(Item.id.in_(sc_ids))
        q_comm = session.query(Community).filter(
            Community.collections.any(Collection.items.any(Item.id.in_(sc_ids)))
        )
        q_file = session.query(File).filter(File.item_id.in_(sc_ids))

        total = q_item.count()
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
    limit = int(request.args.get("limit", 15))
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
    limit = min(int(request.args.get("limit", 10)), 50)
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
    session = SessionLocal()
    try:
        rows = (
            session.query(
                Community.name, Item.dc_rights, func.count(Item.id).label("count")
            )
            .join(Item.collections)
            .join(Collection.community)
            .group_by(Community.name, Item.dc_rights)
            .all()
        )
        result = {}
        for faculty, rights, count in rows:
            if faculty not in result:
                result[faculty] = {"open": 0, "restricted": 0}
            if rights and "openAccess" in rights:
                result[faculty]["open"] += count
            else:
                result[faculty]["restricted"] += count
        return jsonify([{"faculty": k, **v} for k, v in result.items()])
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
    limit = min(int(request.args.get("limit", 50)), 200)
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
                "staff_count": len(inst.staff_names),
            }
        )
    return jsonify(results)


@app.route("/api/analytics/authors-search")
def authors_search():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 10))
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
    top_n = min(int(request.args.get("top_n", 60)), 150)
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
        items = author.items
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
    session = SessionLocal()
    try:
        institution = request.args.get("institution", "").strip()
        q = session.query(Item)
        if institution:
            q = q.filter(Item.institution.ilike(f"%{institution}%"))
        items = q.all()
        TIER1 = __import__("re").compile(
            r"\b(yoruba|igbo|hausa|pidgin|efik|tiv|fulani|ibibio|ijaw|kanuri|sociolinguistics|lexicography|phonology|phonetics|morphosyntax|oral tradition|oral literature|oral poetry|oral narrative|proverbs|folklore|folktale|griot|african literature|nigerian literature|postcolonial literature|literary criticism|literary theory|narratology|language policy|multilingualism|bilingualism|code.switching|indigenous language|vernacular|dialect continuum|pragmatics|discourse analysis|stylistics|nollywood|yoruba drama|african theatre)\b",
            __import__("re").IGNORECASE,
        )
        TIER2 = __import__("re").compile(
            r"\b(morphology|syntax|semantics|translation|literary|language|linguistic|dialect|narrative|discourse|rhetoric|poetry|prose|fiction|novel|drama|theatre|culture|cultural identity|cultural heritage|african studies|humanities)\b",
            __import__("re").IGNORECASE,
        )
        EXCLUDE = __import__("re").compile(
            r"\b(machine learning|deep learning|neural network|artificial intelligence|clinical trial|randomized|patient|hospital|surgery|cancer|tumor|cardiovascular|hypertension|diabetes|preeclampsia|concrete|cement|compressive strength|tensile|alloy|composite|carbon emission|ecological footprint|gdp|economic growth|galaxy|astrophysic|ionosphere|plasma|quantum|semiconductor|mpox|covid|sars|influenza|malaria|hiv|antibiotic|cybersecurity|blockchain|iot|cloud computing|petroleum|crude oil|refinery|corrosion|mentoring|capacity building|faculty development)\b",
            __import__("re").IGNORECASE,
        )
        STOP = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "have",
            "been",
            "were",
            "their",
            "which",
            "these",
            "about",
            "other",
            "into",
            "than",
            "more",
            "such",
            "some",
            "what",
            "when",
            "where",
            "there",
            "also",
            "using",
            "used",
            "study",
            "show",
            "paper",
            "research",
            "analysis",
            "findings",
            "results",
            "between",
            "effect",
            "impact",
            "based",
            "data",
            "method",
            "approach",
            "model",
            "system",
            "review",
            "case",
            "report",
        }
        matches = []
        keyword_counts = {}
        for item in items:
            try:
                title = item.title or ""
                abstract = item.abstract or ""
                text = (title + " " + abstract).lower()
                if EXCLUDE.search(text):
                    continue
                t1 = TIER1.findall(text)
                t2 = TIER2.findall(text)
                score = len(t1) * 2 + len(t2)
                if score < 2:
                    continue
                if not t1 and len(t2) < 3:
                    continue
                words = __import__("re").findall(r"\b[a-z]{5,}\b", text)
                for word in words:
                    if word not in STOP:
                        keyword_counts[word] = keyword_counts.get(word, 0) + 1
                matches.append(
                    {
                        "id": item.id,
                        "title": item.title,
                        "year": (
                            item.publication_date.year
                            if item.publication_date
                            else None
                        ),
                        "authors": [a.name for a in item.authors[:4]],
                        "is_oa": "openAccess" in (item.dc_rights or ""),
                        "score": score,
                        "matched_terms": list(set(t1 + t2))[:6],
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
                    "Total Papers",
                    "Total Authors",
                    "OA Rate %",
                    "TK Rate %",
                    "Patent Rate %",
                    "African Lang Rate %",
                    "Growth Rate %",
                    "Papers/Author",
                    "DocID Coverage %",
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
                        m.get("tk_rate", 0),
                        m.get("patent_rate", 0),
                        m.get("african_lang_rate", 0),
                        m.get("growth_rate", 0),
                        m.get("papers_per_author", 0),
                        m.get("docid_coverage", 0),
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
    """Get citation data for a paper."""
    try:
        from uraas.services.citation_tracker import get_paper_citations

        return jsonify(get_paper_citations(item_id))
    except Exception as e:
        logger.error(f"get_citations {item_id}: {e}")
        return jsonify({"error": str(e)}), 500


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

        limit = min(int(request.args.get("limit", 50)), 200)
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
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
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


@app.route("/api/analytics/patent-velocity")
def patent_velocity():
    return jsonify(analytics.get_patent_velocity())


@app.route("/api/analytics/docid-coverage")
def docid_coverage():
    return jsonify(analytics.get_docid_coverage())


@app.route("/api/analytics/special-collections")
def special_collections():
    institution = request.args.get("institution", None)
    return jsonify(analytics.get_special_collections_metrics(institution=institution))


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


@app.route("/api/analytics/au-charter-alignment")
def au_charter_alignment():
    """
    Score the repository against all 9 AU Charter for African Cultural Renaissance targets.
    Returns per-target count, compliance rate, top matched papers, and metadata.
    Query params: ?institution=unilag (optional)
    """
    session = SessionLocal()
    try:
        from uraas.utils.ai_classifier import AU_CHARTER_TARGETS, classify_au_targets

        institution = request.args.get("institution", "").strip().lower()
        from uraas.analytics.engine import analytics as _analytics

        inst_name = (
            _analytics._resolve_institution_name(institution) if institution else None
        )

        query = session.query(Item)
        if inst_name:
            query = query.filter(Item.institution.ilike(f"%{inst_name}%"))
        items = query.all()
        total = len(items)

        # Aggregate per-target scores
        target_results = {
            num: {"count": 0, "top_papers": []} for num in AU_CHARTER_TARGETS
        }

        for item in items:
            results = classify_au_targets(
                item.title or "", item.abstract or "", item.dc_subject or ""
            )
            for r in results:
                n = r["target_number"]
                target_results[n]["count"] += 1
                if len(target_results[n]["top_papers"]) < 3:
                    target_results[n]["top_papers"].append(
                        {
                            "id": item.id,
                            "title": item.title or "Untitled",
                            "matched_keywords": r["matched_keywords"][:4],
                        }
                    )

        output = []
        for num, defn in AU_CHARTER_TARGETS.items():
            count = target_results[num]["count"]
            output.append(
                {
                    "target_number": num,
                    "target_name": defn["name"],
                    "count": count,
                    "compliance_rate": round(count / total * 100, 1) if total else 0,
                    "top_papers": target_results[num]["top_papers"],
                    "total_papers": total,
                }
            )

        return jsonify(
            {
                "targets": output,
                "total_papers_analyzed": total,
                "institution_filter": inst_name or "All Institutions",
            }
        )
    except Exception as e:
        logger.error(f"au_charter_alignment: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


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


#  DocID stats


@app.route("/api/docid/stats")
def docid_stats():
    session = SessionLocal()
    try:
        total = session.query(Item).count()
        with_docid = session.query(Item).filter(Item.docid.isnot(None)).count()
        return jsonify(
            {
                "total_docid_papers": with_docid,
                "docid_coverage": round(with_docid / total * 100, 1) if total else 0,
            }
        )
    finally:
        session.close()


#  Export


@app.route("/api/export/papers.csv")
def export_csv():
    session = SessionLocal()
    try:
        items = session.query(Item).order_by(desc(Item.created_at)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "DocID",
                "Title",
                "Authors",
                "DOI",
                "Year",
                "Faculty",
                "Open Access",
                "Source",
            ]
        )
        for i in items:
            authors = "; ".join(a.name for a in i.authors)
            faculty = i.collections[0].community.name if i.collections else ""
            year = i.publication_date.year if i.publication_date else ""
            writer.writerow(
                [
                    i.id,
                    i.docid or "",
                    i.title or "",
                    authors,
                    i.doi or "",
                    year,
                    faculty,
                    "Yes" if "openAccess" in (i.dc_rights or "") else "No",
                    i.source_repository or "",
                ]
            )
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=uraas_papers.csv"},
        )
    finally:
        session.close()


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
        # Default ON — heavy bias toward Special Collections in every crawl.
        boost_special = bool(data.get("boost_special", True))
        sc_only = bool(data.get("sc_only", False))
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


@app.route("/api/docid-crawler/start", methods=["POST"])
def start_docid_crawler():
    global docid_crawler_process
    with docid_crawler_lock:
        if docid_crawler_process and docid_crawler_process.poll() is None:
            return (
                jsonify(
                    {"status": "error", "message": "DocID crawler already running"}
                ),
                400,
            )
        data = request.get_json() or {}
        target = min(max(int(data.get("target", 50)), 1), 200)
        try:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            # Note: We are currently using the multi-institution crawler as the base for all crawls
            # If crawl_unilag_repository.py is missing, we use crawl_multi_institution.py --institutions unilag
            script_path = os.path.join(
                project_root, "scripts", "crawl_multi_institution.py"
            )

            process = subprocess.Popen(
                [
                    __import__("sys").executable,
                    script_path,
                    "--target",
                    str(target),
                    "--institutions",
                    "unilag",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            docid_crawler_process = process
            thread = threading.Thread(
                target=docid_crawler_monitor, args=(process,), daemon=True
            )
            thread.start()
            return jsonify(
                {
                    "status": "success",
                    "message": f"DocID crawler started  target {target} papers",
                }
            )
        except FileNotFoundError:
            return (
                jsonify(
                    {"status": "error", "message": "DocID crawler script not found"}
                ),
                500,
            )
        except Exception as e:
            logger.error("start_docid_crawler: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/docid-crawler/stop", methods=["POST"])
def stop_docid_crawler():
    global docid_crawler_process
    with docid_crawler_lock:
        if docid_crawler_process and docid_crawler_process.poll() is None:
            docid_crawler_process.terminate()
            docid_crawler_process = None
            return jsonify({"status": "success", "message": "DocID crawler stopped"})
        return jsonify({"status": "warning", "message": "No DocID crawler running"})


@app.route("/api/docid-crawler/status")
def docid_crawler_status():
    with docid_crawler_lock:
        running = (
            docid_crawler_process is not None and docid_crawler_process.poll() is None
        )
    return jsonify({"status": "running" if running else "idle"})


#  Health Check Endpoint for Render


@app.route("/health")
def health_check():
    """
    Health check endpoint for Render monitoring.
    Returns 200 if operational, 503 if critical services are down.
    """
    from datetime import datetime

    from sqlalchemy import text

    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
    }

    # Check database connectivity
    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        session.close()
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
        logger.error(f"Database health check failed: {str(e)}")

    # Check disk space on persistent volume
    try:
        storage_path = config.STORAGE_PATH
        if os.path.exists(storage_path):
            import shutil

            stat = shutil.disk_usage(storage_path)
            free_gb = stat.free / (1024**3)
            health_status["checks"]["disk_space_gb"] = round(free_gb, 2)
            if free_gb < 1:  # Less than 1GB free
                health_status["status"] = "unhealthy"
                health_status["checks"]["disk_space"] = "critical"
        else:
            health_status["checks"]["disk_space"] = "storage path not found"
    except Exception as e:
        health_status["checks"]["disk_space"] = f"error: {str(e)}"

    # Return appropriate status code
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
