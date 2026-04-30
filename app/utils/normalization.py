import re

_JUNK_RE = re.compile(r"[^A-Z0-9]")


def normalize_article_for_store(article: str) -> str:
    """Normalize an article code before saving to storage.

    Strips whitespace, uppercases, collapses separators,
    removes trailing punctuation.
    """
    s = article.strip().upper()
    s = re.sub(r"[\s]+", " ", s)
    s = re.sub(r"[-]{2,}", "-", s)
    s = s.strip("-.,;:!? ")
    return s


def normalize_article_for_search(article: str) -> str:
    """Normalize an article code for comparison/search.

    Removes all non-alphanumeric characters so that
    'P-551039', 'P 551039' and 'P551039' match the same key.
    """
    s = article.strip().upper()
    return _JUNK_RE.sub("", s)
