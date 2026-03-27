# core/search.py
from storage.sqlite_fts import SqliteFtsStore
from storage.models import SessionFragment
from config import DEFAULT_SEARCH_LIMIT, CONTEXT_WINDOW


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
            fts_query = " OR ".join(query.split())
            results = self.store.search(
                fts_query, project=project, agent_type=agent_type,
                days=days, role=role, limit=limit,
            )
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
        fts_query = " OR ".join(query.split())
        keyword_results = self.store.search(fts_query, **filters, limit=20)
        semantic_results = (
            self.vector_store.search(query, **filters, limit=20)
            if self.vector_store else []
        )

        # Score by position
        scores: dict[int, float] = {}
        for rank, r in enumerate(keyword_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (k + rank + 1)
        for rank, r in enumerate(semantic_results):
            scores[r.id] = scores.get(r.id, 0) + 1.0 / (k + rank + 1)

        # Build result lookup
        all_results = {r.id: r for r in keyword_results}
        all_results.update({r.id: r for r in semantic_results})

        # Sort by RRF score
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [all_results[i] for i in sorted_ids]
