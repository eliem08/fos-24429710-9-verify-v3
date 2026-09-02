"""Tests for dependency hygiene and separation of dev dependencies."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_requirements_contains_no_test_packages():
    req_file = REPO_ROOT / "requirements.txt"
    assert req_file.exists()
    content = req_file.read_text(encoding="utf-8").lower()

    test_only_packages = ["pytest", "pytest-asyncio", "pytest-cov", "pytest-mock", "coverage", "tox"]
    lines = [line.strip().split("=")[0].split(">")[0].split("<")[0].strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    for pkg in test_only_packages:
        assert pkg not in lines, f"Test-only package '{pkg}' found in production requirements.txt"


def test_requirements_dev_contains_test_packages():
    dev_req_file = REPO_ROOT / "requirements-dev.txt"
    assert dev_req_file.exists()
    content = dev_req_file.read_text(encoding="utf-8").lower()
    assert "pytest" in content
