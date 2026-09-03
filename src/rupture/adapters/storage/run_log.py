"""JSONL run log implementing the :class:`~rupture.ports.Tracker` port.

One JSON object per line, appended; never rewritten. Default location is
``data/forecasts/<region>/runs.jsonl`` but the path is the caller's choice.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rupture.ports import RunRecord


class JsonlTracker:
    """Append-only run log. Reads are full scans; the files are small."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def default_path(data_dir: Path, region_id: str) -> Path:
        return Path(data_dir) / "forecasts" / region_id / "runs.jsonl"

    def log(self, record: RunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.canonical_json())
            fh.write("\n")

    def records(
        self, *, kind: str | None = None, region_id: str | None = None
    ) -> Iterable[RunRecord]:
        if not self.path.exists():
            return []
        out: list[RunRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = RunRecord.model_validate_json(line)
            if kind is not None and rec.kind != kind:
                continue
            if region_id is not None and rec.region_id != region_id:
                continue
            out.append(rec)
        return out
