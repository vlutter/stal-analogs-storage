import logging

from app.repositories.sheets_repository import SheetsRepository
from app.schemas.search import SearchByStalResult, SearchResult
from app.utils.normalization import normalize_article_for_search, normalize_article_for_store

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, repo: SheetsRepository | None = None) -> None:
        self._repo = repo or SheetsRepository()

    def search_by_alias(self, article: str) -> SearchResult:
        """Search across all alias columns; return the matching STAL code."""
        query_norm = normalize_article_for_search(article)
        if not query_norm:
            return SearchResult(query=article, found=False)

        for row in self._repo.get_all_rows():
            for alias in row.aliases:
                if normalize_article_for_search(alias) == query_norm:
                    return SearchResult(
                        query=article,
                        found=True,
                        stal_code=row.stal_code,
                        matched_alias=alias,
                    )
            if normalize_article_for_search(row.stal_code) == query_norm:
                return SearchResult(
                    query=article,
                    found=True,
                    stal_code=row.stal_code,
                    matched_alias=row.stal_code,
                )

        return SearchResult(query=article, found=False)

    def search_by_stal(self, article: str) -> SearchByStalResult:
        """Look up a record by its STAL code."""
        stal = normalize_article_for_store(article)
        row = self._repo.get_row_by_stal(stal)
        if row is None:
            return SearchByStalResult(query=article, found=False)
        return SearchByStalResult(
            query=article,
            found=True,
            stal_code=row.stal_code,
            aliases=row.aliases,
        )
