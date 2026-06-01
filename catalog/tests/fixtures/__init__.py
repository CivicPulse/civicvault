from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "bcsd"


def fixture_text(meeting: str, name: str) -> str:
    """Read a committed BCSD fixture file, e.g. fixture_text("committee", "minutes.md")."""
    return (FIXTURES_DIR / meeting / name).read_text(encoding="utf-8")
