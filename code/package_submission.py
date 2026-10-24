"""Build code.zip at the repository root.

Contents: README.md, code/ (source, tests, prompts, OCR cache, evaluation reports and custom
cases) and evaluation/ (identical copies of the two reports, for the AGENTS.md path).
Excluded: dataset/, .git/, virtual environments, caches, secrets/.env files, nested archives,
generated outputs.

    python code/package_submission.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "code.zip"
EXCLUDED_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".pyc", ".pyo"}
EXCLUDED_NAMES = {".env", ".DS_Store"}
REPORTS = ("evaluation_report.md", "usage_report.md")


def wanted(path: Path) -> bool:
    rel = path.relative_to(REPO)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES or path.name in EXCLUDED_NAMES or path.name.startswith(".env"):
        return False
    return path.is_file()


def build() -> list[str]:
    names = []
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(REPO / "README.md", "README.md")
        names.append("README.md")
        for path in sorted((REPO / "code").rglob("*")):
            if wanted(path):
                arc = path.relative_to(REPO).as_posix()
                zf.write(path, arc)
                names.append(arc)
        for report in REPORTS:
            src = REPO / "code" / "evaluation" / report
            zf.write(src, f"evaluation/{report}")
            names.append(f"evaluation/{report}")
    return names


if __name__ == "__main__":
    files = build()
    print(f"wrote {OUT} with {len(files)} files")
