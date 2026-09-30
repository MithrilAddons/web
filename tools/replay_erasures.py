"""Reapply the preserved erasure ledger to restored databases before starting the service."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mithril_web.auth import AuthStore  # noqa: E402
from mithril_web.moderation import Moderation  # noqa: E402
from mithril_web.privacy import Privacy  # noqa: E402
from mithril_web.record_store import DAY, RecordStore  # noqa: E402


def replay(auth_path, backup_created, now=None):
    now = now or datetime.now(UTC)
    if backup_created.tzinfo is None or not 0 <= (now - backup_created).total_seconds() < 7 * DAY:
        raise ValueError("Only backups less than seven days old may be restored")
    auth_path = Path(auth_path).resolve()
    for path in (
        auth_path,
        auth_path.with_name("records.sqlite3"),
        auth_path.with_name("erasures.jsonl"),
    ):
        if not path.is_file():
            raise ValueError("Restore both databases and preserve the current erasure ledger")
    auth = AuthStore(auth_path)
    records = RecordStore(auth_path.with_name("records.sqlite3"))
    try:
        Privacy(auth, Moderation(records), auth_path)
    finally:
        records.close()
        auth.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("auth_database", type=Path)
    parser.add_argument(
        "--backup-created",
        required=True,
        type=datetime.fromisoformat,
        help="UTC timestamp recorded when the SQLite backups were taken",
    )
    args = parser.parse_args()
    replay(args.auth_database, args.backup_created)
    print("Erasure replay completed. Start only a compatible service version.")
