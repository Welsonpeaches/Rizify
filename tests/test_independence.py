from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def python_sources() -> list[Path]:
    paths: list[Path] = []
    for base in (
        ROOT / "acidify-core" / "src",
        ROOT / "rizify" / "src",
    ):
        paths.extend(path for path in base.rglob("*.py") if path.is_file())
    return paths


def test_no_yogurt_imports_or_subprocesses() -> None:
    pattern = re.compile(
        r"(?:\bimport\s+yogurt\b|\bfrom\s+yogurt\b|\bsubprocess\b|"
        r"\bos\.system\b|\brizify\.kexe\b)",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in python_sources():
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_no_signing_algorithm_or_wrapper_node() -> None:
    pattern = re.compile(
        r"(?:wrapper\.node|sec_sign\s*=|def\s+.*sign.*sha|"
        r"class\s+.*SignatureAlgorithm)",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in python_sources():
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_sign_provider_uses_external_endpoint() -> None:
    source = (ROOT / "acidify-core" / "src" / "acidify_core" / "sign.py").read_text(
        encoding="utf-8"
    )
    assert 'urljoin(base, "api/sign/sec-sign")' in source
