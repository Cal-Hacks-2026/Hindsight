"""GE progress (I-13): Cal-GETC and IGETC areas from a college's ASSIST lists × the transcript."""

from app.services.assist import get_service

from .lists import GeListStore
from .progress import progress
from .rules import Pattern

_store: GeListStore | None = None


def get_store() -> GeListStore:
    """Follows the ASSIST service's client, so a swapped service (tests) gets its own store."""
    global _store
    client = get_service().client
    if _store is None or _store.client is not client:
        _store = GeListStore.from_env(client)
    return _store


def set_store(store: GeListStore | None) -> None:
    global _store
    _store = store


__all__ = ["GeListStore", "Pattern", "get_store", "progress", "set_store"]
