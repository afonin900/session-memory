# core/search.py
from datetime import datetime, timezone
from storage.sqlite_fts import SqliteFtsStore, _FTS5_OPERATORS
from storage.models import SessionFragment
from config import DEFAULT_SEARCH_LIMIT, CONTEXT_WINDOW

# Recency decay: half-life in days. Results older than this get halved recency boost.
RECENCY_HALF_LIFE_DAYS = 14


def _has_fts5_operators(query: str) -> bool:
    """Return True if query already contains explicit FTS5 operators."""
    tokens = query.split()
    return any(t in _FTS5_OPERATORS for t in tokens)


class SearchEngine:
    def __init__(
        self,
        store: SqliteFtsStore,
        vector_store=None,  # LanceDB, added in Phase 2
    ):
        self.store = store
        self.vector_store = vector_store

    def search(
        self,
        query: str,
        mode: str = "keyword",  # keyword, semantic, all
        project: str | None = None,
        agent_type: str | None = None,
        days: int | None = None,
        role: str | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[SessionFragment]:
        """Search sessions and return results with context windows."""

        if mode == "keyword":
            # FTS5 default is AND — use OR for broader matching
            # But if user supplied explicit operators, pass query as-is
            if _has_fts5_operators(query):
                fts_query = query
            else:
                fts_query = " OR ".join(query.split())
            results = self.store.search(
                fts_query, project=project, agent_type=agent_type,
                days=days, role=role, limit=limit,
            )
            # Also search knowledge base
            try:
                kb_results = self.store.search_knowledge(
                    fts_query, project=project, days=days, limit=5,
                )
                results.extend(kb_results)
            except Exception:
                pass  # knowledge table may not exist yet
        elif mode == "semantic":
            if not self.vector_store:
                raise RuntimeError("Semantic search requires vector store (install Phase 2)")
            results = self.vector_store.search(
                query, project=project, agent_type=agent_type,
                days=days, role=role, limit=limit,
            )
        elif mode == "all":
            results = self._merged_search(
                query, project=project, agent_type=agent_type,
                days=days, role=role, limit=limit,
            )
        else:
            raise ValueError(f"Unknown search mode: {mode}")

        # Build context windows
        fragments = []
        seen_ids = set()
        for result in results:
            if result.id in seen_ids:
                continue
            seen_ids.add(result.id)
            # Knowledge results don't have session context
            if result.agent_type == "knowledge":
                fragments.append(SessionFragment(
                    match=result,
                    before=[],
                    after=[],
                    session_id=result.session_id,
                    project=result.project,
                ))
                continue
            try:
                fragment = self.store.get_context(result.id, window=CONTEXT_WINDOW)
                fragments.append(fragment)
            except ValueError:
                # Stale ID from vector store — skip silently
                continue

        return fragments[:limit]

    def _merged_search(
        self,
        query: str,
        project: str | None = None,
        agent_type: str | None = None,
        days: int | None = None,
        role: str | None = None,
        limit: int = 20,
    ) -> list:
        """Reciprocal Rank Fusion of keyword + semantic results."""
        k = 60  # RRF constant
        filters = dict(project=project, agent_type=agent_type, days=days, role=role)

        # FTS5 default is AND — use OR for natural language queries
        # But if user supplied explicit operators, pass query as-is
        if _has_fts5_operators(query):
            fts_query = query
        else:
            fts_query = " OR ".join(query.split())
        keyword_results = self.store.search(fts_query, **filters, limit=20)
        semantic_results = (
            self.vector_store.search(query, **filters, limit=20)
            if self.vector_store else []
        )

        # Knowledge base results
        knowledge_results = self.store.search_knowledge(
            query, project=project, days=days, limit=10,
        )

        # Score by position
        scores: dict[int, float] = {}
        for rank, r in enumerate(keyword_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (k + rank + 1)
        for rank, r in enumerate(semantic_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (k + rank + 1)
        for rank, r in enumerate(knowledge_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (k + rank + 1)

        # Build result lookup
        all_results = {r.id: r for r in keyword_results}
        all_results.update({r.id: r for r in semantic_results})
        all_results.update({r.id: r for r in knowledge_results})

        # Recency boost: newer results get higher score
        now = datetime.now(timezone.utc)
        for rid, result in all_results.items():
            try:
                ts = result.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = max(0, (now - ts).days)
                # Exponential decay: halves every RECENCY_HALF_LIFE_DAYS
                recency = 1.0 / (1 + age_days / RECENCY_HALF_LIFE_DAYS)
                scores[rid] = scores.get(rid, 0) + recency * 0.01
            except (TypeError, AttributeError):
                pass

        # Sort by RRF score (with recency boost)
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [all_results[i] for i in sorted_ids]
