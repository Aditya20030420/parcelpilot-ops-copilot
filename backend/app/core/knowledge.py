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
        self._known_ids: set[str] | None = None

    def _hydrate_pack(self) -> None:
        """If the data pack isn't on disk, rehydrate it from a base64 zip provided out of
        band (so the pack stays out of the public repo). Sources, in order:
          - env DATA_PACK_B64        (inline base64 of a zip)
          - env DATA_PACK_B64_FILE   (path to a file containing that base64)
          - /etc/secrets/datapack.b64  (Render secret file default)
        Extracts into settings.data_dir.
        """
        import base64
        import io
        import os
        import zipfile

        data_dir = settings.data_dir
        if data_dir.exists() and (any(data_dir.glob("*.pdf")) or any(data_dir.glob("*.xlsx"))):
            return  # pack already present locally

        b64 = os.environ.get("DATA_PACK_B64")
        if not b64:
            candidates = [os.environ.get("DATA_PACK_B64_FILE"), "/etc/secrets/datapack.b64"]
            for path in candidates:
                if path and os.path.exists(path):
                    b64 = open(path, "r", encoding="utf-8").read()
                    break
        if not b64:
            return
        try:
            raw = base64.b64decode(b64.strip())
            data_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                zf.extractall(str(data_dir))
            print(f"[ingest] rehydrated data pack into {data_dir}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] failed to rehydrate data pack: {exc}")

    def load(self) -> None:
        self._hydrate_pack()
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

    def known_ids(self) -> set[str]:
        """All real order/ticket/account IDs (and account names) found in the data, cached.
        Used to catch IDs the model might invent."""
        if self._known_ids is None:
            import re

            ids: set[str] = set()
            for tbl in self.data.tables.values():
                for row in tbl.rows:
                    for col, val in row.items():
                        if val in (None, ""):
                            continue
                        if re.search(r"(_id$|^id$|order|ticket|account)", col, re.I):
                            ids.add(str(val).strip())
            self._known_ids = ids
        return self._known_ids

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
