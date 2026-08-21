"""Loads and holds the document + structured stores for the whole app."""
from __future__ import annotations

import datetime as dt

from ..config import settings
from ..ingest.documents import DocumentStore
from ..ingest.structured import StructuredStore


class Knowledge:
    def __init__(self) -> None:
        self.docs = DocumentStore()
        self.data = StructuredStore()
        self.loaded = False
        self.source_dir = settings.data_dir

    def load(self) -> None:
        data_dir = settings.data_dir
        # Fall back to the generated sample pack if the real data/ folder is empty, so the
        # app is runnable out-of-the-box for a demo. Drop the official pack into data/ to
        # override.
        has_real = data_dir.exists() and (
            any(data_dir.glob("*.pdf")) or any(data_dir.glob("*.xlsx"))
        )
        if not has_real:
            sample = settings.data_dir.parent / "sample_data"
            if sample.exists():
                data_dir = sample
                self.source_dir = sample
        else:
            self.source_dir = data_dir
        if data_dir.exists():
            self.docs.load_dir(data_dir)
            for xlsx in data_dir.glob("*.xlsx"):
                self.data.load_file(xlsx)
        self.loaded = True

    @property
    def snapshot_time(self) -> dt.datetime:
        """Reference 'now' for all time math. Falls back to real now if README lacks one."""
        return self.data.snapshot_time or dt.datetime.now()

    def status(self) -> dict:
        return {
            "loaded": self.loaded,
            "documents": self.docs.stats(),
            "structured": self.data.stats(),
            "snapshot_time": self.snapshot_time.isoformat(),
        }


knowledge = Knowledge()
