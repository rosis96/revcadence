"""Regression checks for the Railway pre-migration/Alembic startup sequence.

Run: python -m tests.test_migration_safety
"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OLD_REVISION = "120b8ef2c964"
HEAD_REVISION = "6d2bc12dbf30"
NEW_TABLES = {"workspace_training_revisions", "workspace_evaluation_cases"}


def run(db_path: Path, *command: str) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "JWT_SECRET": "migration-safety-test",
    }
    subprocess.run(
        [sys.executable, *command],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def revision(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]


def check_normal_startup(directory: Path) -> None:
    db_path = directory / "normal.db"
    run(db_path, "-m", "alembic", "upgrade", OLD_REVISION)
    run(db_path, "-m", "scripts.premigrate")
    assert NEW_TABLES.isdisjoint(tables(db_path)), (
        "premigrate must not create tables owned by pending Alembic migrations"
    )
    run(db_path, "-m", "alembic", "upgrade", "head")
    assert NEW_TABLES.issubset(tables(db_path))
    assert revision(db_path) == HEAD_REVISION
    print("✓ normal Railway startup leaves new-table creation to Alembic")


def check_recovery_startup(directory: Path) -> None:
    db_path = directory / "recovery.db"
    run(db_path, "-m", "alembic", "upgrade", OLD_REVISION)

    # Reproduce the failed release: the legacy additive sync created mapped
    # tables while alembic_version still pointed at the preceding revision.
    run(db_path, "-c", "from app.db import migrate; migrate()")
    assert NEW_TABLES.issubset(tables(db_path))
    assert revision(db_path) == OLD_REVISION

    # The repaired migration must accept those existing tables and advance.
    run(db_path, "-m", "alembic", "upgrade", "head")
    assert NEW_TABLES.issubset(tables(db_path))
    assert revision(db_path) == HEAD_REVISION
    print("✓ partially created Railway schema recovers without deleting data")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        check_normal_startup(directory)
        check_recovery_startup(directory)
    print("\n2/2 migration safety checks passed")


if __name__ == "__main__":
    main()
