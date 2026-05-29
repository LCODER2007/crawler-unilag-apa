"""
Advanced Search Service
Implements Boolean operators, field-specific queries, and full-text search.
Comparable to Scopus/Web of Science search capabilities.
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from sqlalchemy import or_, and_, not_, func, text
from uraas.database import SessionLocal, Item, Author, Collection, Community, db_year

logger = logging.getLogger(__name__)


class SearchQuery:
    """Parse and execute advanced search queries."""

    @staticmethod
    def ast_to_string(node) -> str:
        if node is None:
            return ""
        node_type = node[0]
        if node_type in ("AND", "OR"):
            return f"({SearchQuery.ast_to_string(node[1])} {node_type} {SearchQuery.ast_to_string(node[2])})"
        elif node_type == "NOT":
            return f"(NOT {SearchQuery.ast_to_string(node[1])})"
        elif node_type == "FIELD_VAL":
            field, val = node[1]
            return f"{field}:{val}"
        elif node_type == "PHRASE":
            return f'"{node[1]}"'
        elif node_type == "TERM":
            return node[1]
        return str(node)

    @staticmethod
    def parse_boolean_query(query: str):
        """
        Parse Boolean search query into structured format (AST).

        Supports:
        - AND, OR, NOT operators
        - Parentheses for grouping
        - Field-specific searches: title:machine, author:smith, year:2020
        - Phrase searches: "machine learning"
        - Wildcards: machin* (suffix), *learning (prefix)

        Returns:
            AST node (tuple)
        """
        query = query.strip()
        if not query:
            return None

        try:
            # Tokenize
            token_specification = [
                ("LPAR", r"\("),
                ("RPAR", r"\)"),
                ("AND", r"\bAND\b"),
                ("OR", r"\bOR\b"),
                ("NOT", r"\bNOT\b"),
                (
                    "FIELD_VAL",
                    r'\b(\w+):(?:(?:"([^"]+)")|(?:\'([^\']+)\')|([^\s\)\(]+))',
                ),
                ("PHRASE", r'"([^"]+)"|\'([^\']+)\''),
                ("TERM", r"[^\s\)\(]+"),
                ("SKIP", r"\s+"),
            ]
            tok_regex = "|".join(
                f"(?P<{name}>{pattern})" for name, pattern in token_specification
            )
            tokens = []
            for mo in re.finditer(tok_regex, query):
                kind = mo.lastgroup
                if kind == "SKIP":
                    continue
                val = mo.group(kind)
                if kind == "FIELD_VAL":
                    field_match = re.match(r"^(\w+):(.*)$", val)
                    field = field_match.group(1).lower()
                    raw_val = field_match.group(2)
                    if (raw_val.startswith('"') and raw_val.endswith('"')) or (
                        raw_val.startswith("'") and raw_val.endswith("'")
                    ):
                        raw_val = raw_val[1:-1]
                    tokens.append(("FIELD_VAL", (field, raw_val)))
                elif kind == "PHRASE":
                    if (val.startswith('"') and val.endswith('"')) or (
                        val.startswith("'") and val.endswith("'")
                    ):
                        val = val[1:-1]
                    tokens.append(("PHRASE", val))
                elif kind == "TERM":
                    tokens.append(("TERM", val))
                else:
                    tokens.append((kind, val))

            # Insert implicit ANDs
            operand_types = {"TERM", "PHRASE", "FIELD_VAL", "RPAR"}
            start_operand_types = {"TERM", "PHRASE", "FIELD_VAL", "LPAR", "NOT"}
            tokens_with_ands = []
            for i, tok in enumerate(tokens):
                if i > 0:
                    prev_tok = tokens[i - 1]
                    if prev_tok[0] in operand_types and tok[0] in start_operand_types:
                        tokens_with_ands.append(("AND", "AND"))
                tokens_with_ands.append(tok)

            # Parse to AST using Shunting-yard
            precedence = {"NOT": 3, "AND": 2, "OR": 1}
            output_stack = []
            operator_stack = []

            for tok_type, val in tokens_with_ands:
                if tok_type in {"TERM", "PHRASE", "FIELD_VAL"}:
                    output_stack.append((tok_type, val))
                elif tok_type == "LPAR":
                    operator_stack.append((tok_type, val))
                elif tok_type == "RPAR":
                    while operator_stack and operator_stack[-1][0] != "LPAR":
                        op = operator_stack.pop()
                        if op[0] == "NOT":
                            if not output_stack:
                                raise ValueError("Invalid NOT query")
                            arg = output_stack.pop()
                            output_stack.append(("NOT", arg))
                        else:
                            if len(output_stack) < 2:
                                raise ValueError(
                                    f"Invalid query: missing arguments for {op[0]}"
                                )
                            right = output_stack.pop()
                            left = output_stack.pop()
                            output_stack.append((op[0], left, right))
                    if not operator_stack:
                        raise ValueError("Mismatched parentheses")
                    operator_stack.pop()  # pop LPAR
                elif tok_type in {"AND", "OR", "NOT"}:
                    while (
                        operator_stack
                        and operator_stack[-1][0] in precedence
                        and precedence[operator_stack[-1][0]] >= precedence[tok_type]
                    ):
                        op = operator_stack.pop()
                        if op[0] == "NOT":
                            if not output_stack:
                                raise ValueError("Invalid NOT query")
                            arg = output_stack.pop()
                            output_stack.append(("NOT", arg))
                        else:
                            if len(output_stack) < 2:
                                raise ValueError(
                                    f"Invalid query: missing arguments for {op[0]}"
                                )
                            right = output_stack.pop()
                            left = output_stack.pop()
                            output_stack.append((op[0], left, right))
                    operator_stack.append((tok_type, val))

            while operator_stack:
                op = operator_stack.pop()
                if op[0] == "LPAR":
                    raise ValueError("Mismatched parentheses")
                if op[0] == "NOT":
                    if not output_stack:
                        raise ValueError("Invalid NOT query")
                    arg = output_stack.pop()
                    output_stack.append(("NOT", arg))
                else:
                    if len(output_stack) < 2:
                        raise ValueError(
                            f"Invalid query: missing arguments for {op[0]}"
                        )
                    right = output_stack.pop()
                    left = output_stack.pop()
                    output_stack.append((op[0], left, right))

            if not output_stack:
                return None
            if len(output_stack) > 1:
                raise ValueError("Invalid query expression")
            return output_stack[0]

        except Exception as e:
            logger.warning(
                f"Boolean parsing failed for query '{query}': {e}. Falling back to simple parsing."
            )
            # Fallback to simple split AND-join
            words = query.split()
            if not words:
                return None
            node = ("TERM", words[0])
            for w in words[1:]:
                node = ("AND", node, ("TERM", w))
            return node

    @staticmethod
    def build_sql_filter(parsed_query, session=None):
        """
        Build SQLAlchemy filter from parsed query.

        Returns:
            SQLAlchemy filter expression
        """
        if parsed_query is None:
            return None

        if session is None:
            session = SessionLocal()

        def evaluate_node(node):
            if node is None:
                return None

            node_type = node[0]
            if node_type == "AND":
                left = evaluate_node(node[1])
                right = evaluate_node(node[2])
                if left is not None and right is not None:
                    return and_(left, right)
                return left or right

            elif node_type == "OR":
                left = evaluate_node(node[1])
                right = evaluate_node(node[2])
                if left is not None and right is not None:
                    return or_(left, right)
                return left or right

            elif node_type == "NOT":
                arg = evaluate_node(node[1])
                if arg is not None:
                    return not_(arg)
                return None

            elif node_type == "FIELD_VAL":
                field, val = node[1]
                return build_field_filter(field, val)

            elif node_type == "PHRASE":
                val = node[1]
                return or_(
                    Item.title.ilike(f"%{val}%"),
                    Item.abstract.ilike(f"%{val}%"),
                    Item.ai_keywords.ilike(f"%{val}%"),
                )

            elif node_type == "TERM":
                val = node[1]
                if "*" in val:
                    sql_val = val.replace("*", "%")
                else:
                    sql_val = f"%{val}%"
                return or_(
                    Item.title.ilike(sql_val),
                    Item.abstract.ilike(sql_val),
                    Item.doi.ilike(sql_val),
                    Item.ai_keywords.ilike(sql_val),
                )
            return None

        def build_field_filter(field, value):
            if "*" in value:
                sql_val = value.replace("*", "%")
            else:
                sql_val = f"%{value}%"

            if field == "title":
                return Item.title.ilike(sql_val)
            elif field == "abstract":
                return Item.abstract.ilike(sql_val)
            elif field == "author":
                return Item.id.in_(
                    session.query(Item.id)
                    .join(Item.authors)
                    .filter(Author.name.ilike(sql_val))
                )
            elif field == "year":
                try:
                    year = int(value)
                    return db_year(Item.publication_date) == str(year)
                except ValueError:
                    return None
            elif field == "doi":
                return Item.doi.ilike(sql_val)
            elif field == "faculty":
                return Item.id.in_(
                    session.query(Item.id)
                    .join(Item.collections)
                    .join(Collection.community)
                    .filter(Community.name.ilike(sql_val))
                )
            elif field == "department":
                return Item.id.in_(
                    session.query(Item.id)
                    .join(Item.collections)
                    .filter(Collection.name.ilike(sql_val))
                )
            elif field == "keyword":
                return or_(
                    Item.ai_keywords.ilike(sql_val), Item.dc_subject.ilike(sql_val)
                )
            elif field == "language":
                return Item.language_code == value.lower()
            elif field == "oa" or field == "openaccess":
                if value.lower() in ("true", "yes", "1"):
                    return Item.dc_rights.like("%openAccess%")
                else:
                    return ~Item.dc_rights.like("%openAccess%")
            else:
                return or_(
                    Item.title.ilike(sql_val),
                    Item.abstract.ilike(sql_val),
                    Item.doi.ilike(sql_val),
                    Item.ai_keywords.ilike(sql_val),
                )

        return evaluate_node(parsed_query)

    @staticmethod
    def execute_search(
        query: str,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "relevance",
        filters: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute advanced search query.

        Args:
            query: Search query string (supports Boolean operators)
            limit: Maximum results to return
            offset: Pagination offset
            sort_by: Sort order ('relevance', 'date', 'citations', 'title')
            filters: Additional filters (year_from, year_to, oa_only, etc.)

        Returns:
            {
                'total': int,
                'results': [paper_dict, ...],
                'query_parsed': str,
                'took_ms': float
            }
        """
        import time

        start_time = time.time()

        session = SessionLocal()
        try:
            # Parse query
            parsed = SearchQuery.parse_boolean_query(query)

            # Build base query
            q = session.query(Item)

            # Apply parsed query filters
            sql_filter = SearchQuery.build_sql_filter(parsed, session)
            if sql_filter is not None:
                q = q.filter(sql_filter)

            # Apply additional filters
            if filters:
                if filters.get("year_from"):
                    q = q.filter(
                        db_year(Item.publication_date) >= str(filters["year_from"])
                    )

                if filters.get("year_to"):
                    q = q.filter(
                        db_year(Item.publication_date) <= str(filters["year_to"])
                    )

                if filters.get("oa_only"):
                    q = q.filter(Item.dc_rights.like("%openAccess%"))

                if filters.get("faculty"):
                    q = (
                        q.join(Item.collections)
                        .join(Collection.community)
                        .filter(Community.name.ilike(f'%{filters["faculty"]}%'))
                    )

                if filters.get("has_pdf"):
                    from uraas.database import File

                    q = q.join(File, File.item_id == Item.id)

            # Get total count
            total = q.count()

            # Apply sorting
            if sort_by == "date":
                q = q.order_by(Item.publication_date.desc().nullslast())
            elif sort_by == "title":
                q = q.order_by(Item.title)
            elif sort_by == "citations":
                # Join with citation metrics if available
                from uraas.services.citation_tracker import CitationMetrics

                q = q.outerjoin(
                    CitationMetrics, CitationMetrics.item_id == Item.id
                ).order_by(CitationMetrics.citation_count.desc().nullslast())
            else:  # relevance (default)
                # Simple relevance: prioritize title matches
                q = q.order_by(Item.created_at.desc())

            # Pagination
            results = q.limit(limit).offset(offset).all()

            # Format results
            formatted_results = []
            for item in results:
                formatted_results.append(
                    {
                        "id": item.id,
                        "title": item.title,
                        "abstract": item.abstract[:300] if item.abstract else None,
                        "doi": item.doi,
                        "url": item.url,
                        "year": (
                            item.publication_date.year
                            if item.publication_date
                            else None
                        ),
                        "authors": [a.name for a in item.authors[:5]],
                        "faculty": (
                            item.collections[0].community.name
                            if item.collections and item.collections[0].community
                            else None
                        ),
                        "department": (
                            item.collections[0].name if item.collections else None
                        ),
                        "is_oa": "openAccess" in (item.dc_rights or ""),
                        "docid": item.docid,
                        "language": item.language_code,
                        "keywords": (
                            item.ai_keywords.split(",")[:5] if item.ai_keywords else []
                        ),
                    }
                )

            took_ms = (time.time() - start_time) * 1000

            return {
                "total": total,
                "results": formatted_results,
                "query_parsed": SearchQuery.ast_to_string(parsed),
                "took_ms": round(took_ms, 2),
                "page": offset // limit + 1,
                "pages": (total + limit - 1) // limit,
            }

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"total": 0, "results": [], "error": str(e), "took_ms": 0}
        finally:
            session.close()

    @staticmethod
    def get_search_suggestions(partial_query: str, field: str = "all") -> List[str]:
        """
        Get autocomplete suggestions for search queries.

        Args:
            partial_query: Partial search term
            field: Field to search ('author', 'keyword', 'faculty', 'all')

        Returns:
            List of suggested completions
        """
        session = SessionLocal()
        try:
            suggestions = []

            if field in ("author", "all"):
                authors = (
                    session.query(Author.name)
                    .filter(Author.name.ilike(f"%{partial_query}%"))
                    .limit(10)
                    .all()
                )
                suggestions.extend([f"author:{a[0]}" for a in authors])

            if field in ("faculty", "all"):
                faculties = (
                    session.query(Community.name)
                    .filter(Community.name.ilike(f"%{partial_query}%"))
                    .limit(5)
                    .all()
                )
                suggestions.extend([f"faculty:{f[0]}" for f in faculties])

            if field in ("keyword", "all"):
                # Extract keywords from papers
                items = (
                    session.query(Item.ai_keywords)
                    .filter(Item.ai_keywords.ilike(f"%{partial_query}%"))
                    .limit(20)
                    .all()
                )

                keywords = set()
                for item in items:
                    if item[0]:
                        for kw in item[0].split(","):
                            kw = kw.strip()
                            if partial_query.lower() in kw.lower():
                                keywords.add(kw)

                suggestions.extend([f"keyword:{k}" for k in list(keywords)[:10]])

            return suggestions[:15]

        finally:
            session.close()


# ── Saved Searches ────────────────────────────────────────────────────────────


class SavedSearch:
    """Manage saved search queries for users."""

    @staticmethod
    def save_search(name: str, query: str, filters: Optional[Dict] = None) -> int:
        """Save a search query for later reuse."""
        # TODO: Implement user authentication first
        # For now, store in a simple table
        pass

    @staticmethod
    def get_saved_searches() -> List[Dict]:
        """Get all saved searches."""
        # TODO: Implement
        pass

    @staticmethod
    def execute_saved_search(search_id: int) -> Dict:
        """Execute a previously saved search."""
        # TODO: Implement
        pass
