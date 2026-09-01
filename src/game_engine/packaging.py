from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PackageReport:
    zip_path: Path
    compressed_bytes: int
    limit_bytes: int
    ok: bool
    warnings: list[str]


def package_game(source_dir: Path, zip_path: Path, limit_bytes: int = 13 * 1024) -> PackageReport:
    source_dir = source_dir.resolve()
    index = source_dir / "index.html"
    if not index.exists():
        raise ValueError("Game source must contain top-level index.html")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    html = index.read_text(errors="ignore")
    if re.search(r"https?://", html):
        warnings.append("index.html contains an external URL; verify competition rules/category allowances.")

    files = [p for p in source_dir.rglob("*") if p.is_file() and ".git" not in p.parts]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(files):
            zf.write(path, path.relative_to(source_dir).as_posix())

    size = os.path.getsize(zip_path)
    return PackageReport(zip_path, size, limit_bytes, size <= limit_bytes, warnings)
