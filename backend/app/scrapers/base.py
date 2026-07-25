from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from app.models.jobs import SourceRecord


class ScrapeError(RuntimeError):
    """Raised when a source cannot produce a trustworthy complete result."""


class BaseJobScraper(ABC):
    source_name: str

    @abstractmethod
    def scrape_all(self) -> Iterator[SourceRecord]:
        """Yield every job currently exposed by the source without filtering."""
