"""Feld-Vault — vom Host freigegebene Dateien (nie überschreiben, kein Pfadausbruch)."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Dict, List

MAX_FILE_BYTES = 64 * 1024 * 1024


def safe_name(name: str) -> str:
    base = os.path.basename(str(name).replace("\\", "/"))
    if base in ("", ".", ".."):
        raise ValueError(f"Ungültiger Dateiname: {name!r}")
    return base


class Vault:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._sha: Dict[tuple, str] = {}

    def list_info(self) -> List[dict]:
        out = []
        for p in sorted(self.dir.iterdir(), key=lambda x: x.name.casefold()):
            if p.is_file():
                out.append({"name": p.name, "size": p.stat().st_size})
        return out

    def store(self, src_path: str | Path) -> str:
        """Kopiert eine Datei in den Vault; bei gleichem Namen wird ' (n)' angehängt."""
        src = Path(src_path)
        if not src.is_file():
            raise FileNotFoundError(f"Keine Datei: {src}")
        if src.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"Datei größer als {MAX_FILE_BYTES // (1024 * 1024)} MB")
        base = safe_name(src.name)
        stem, suffix = Path(base).stem, Path(base).suffix
        candidate, n = base, 0
        while True:
            try:
                with open(src, "rb") as fin, open(self.dir / candidate, "xb") as fout:
                    shutil.copyfileobj(fin, fout, 1024 * 1024)
                return candidate
            except FileExistsError:
                n += 1
                candidate = f"{stem} ({n}){suffix}"

    def path_of(self, name: str) -> Path:
        vault = self.dir.resolve()
        p = vault / safe_name(name)
        if not p.is_file() or p.resolve().parent != vault:
            raise FileNotFoundError(f"Nicht im Vault: {name}")
        return p

    def info(self, name: str, chunk_size: int) -> dict:
        p = self.path_of(name)
        st = p.stat()
        key = (p.name, st.st_mtime_ns, st.st_size)
        if key not in self._sha:
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(block)
            self._sha[key] = h.hexdigest()
        chunks = max(1, -(-st.st_size // chunk_size))
        return {"name": p.name, "size": st.st_size, "chunks": chunks,
                "chunk_size": chunk_size, "sha256": self._sha[key]}

    def read_chunk(self, name: str, idx: int, chunk_size: int) -> bytes:
        p = self.path_of(name)
        with open(p, "rb") as fh:
            fh.seek(idx * chunk_size)
            return fh.read(chunk_size)
