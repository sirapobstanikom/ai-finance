import re
from pathlib import Path


class RawStore:
    """Content-addressed bytes under data/raw. Callers cannot choose the path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content_hash: str, data: bytes, suffix: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{64}", content_hash) is None:
            raise ValueError("content hash must be 64 hex characters")
        safe_suffix = suffix if suffix in {".pdf", ".txt", ".md"} else ".bin"
        path = self.root / content_hash[:2] / f"{content_hash}{safe_suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError("refusing to write outside the raw store")
        if not path.exists():
            path.write_bytes(data)
        return path
