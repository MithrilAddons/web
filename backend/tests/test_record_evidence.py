import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from mithril_web.record_store import DAY, RecordStore
from mithril_web.solo_evidence import ScoreEvidence, SoloProgress, SoloStart, TerminalReport

UUID = "a" * 32
OTHER = "b" * 32
LOW = dict(
    completed=10,
    cleared=33,
    secrets=20.0,
    crypts=5,
    puzzles=3,
    solved=0,
    deaths=0,
    blood_included=False,
    in_boss=False,
    mimic=True,
    prince=False,
    bat=False,
)
HIGH = {**LOW, "completed": 30, "cleared": 100, "secrets": 100.0, "solved": 3}


@pytest.fixture
def storage(tmp_path):
    now = [100_000.0]
    store = RecordStore(tmp_path / "records.db", clock=lambda: now[0])
    try:
        yield store, now
    finally:
        store.close()


def start(store):
    return store.start(UUID, SoloStart(version=2, floor="F7", elapsed_ms=0, ticks=0, paul=False))


def update(store, now, attempt, seq, elapsed, *, complete=False, **changes):
    now[0] += 5
    data = dict(
        version=2,
        attempt_id=attempt["attempt_id"],
        nonce=attempt["nonce"],
        sequence=seq,
        elapsed_ms=elapsed,
        ticks=elapsed // 50,
        roster=[UUID],
        dead=False,
        valid=True,
        evidence=HIGH if complete else LOW,
        complete=complete,
    )
    return store.progress(UUID, SoloProgress.model_validate({**data, **changes}))


def finish(store, now):
    attempt = start(store)
    for sequence in range(1, 4):
        attempt = update(store, now, attempt, sequence, sequence * 5000, complete=sequence == 3)
    assert attempt["status"] == "accepted"
    return attempt


def test_score_recomputed_from_inputs_and_unknown_fields_fail_closed():
    assert ScoreEvidence(**LOW).score(5000, False) < 300
    assert ScoreEvidence(**HIGH).score(15000, False) == 307
    assert ScoreEvidence(**HIGH).score(15000, True) == 317
    assert ScoreEvidence(**{**HIGH, "secrets": None}).score(15000, False) is None
    assert ScoreEvidence(**{**HIGH, "solved": 4}).score(15000, False) is None


def test_score_matches_shared_client_vectors():
    cases = json.loads((Path(__file__).parents[2] / "contracts/solo-score-v2.json").read_text())
    for case in cases:
        assert (
            ScoreEvidence(**case["evidence"]).score(case["elapsed_ms"], case["paul"])
            == case["score"]
        ), case["name"]


def test_live_sequence_stores_evidence_and_only_finish_creates_pb(storage):
    store, now = storage
    attempt = start(store)
    first_nonce = attempt["nonce"]
    for sequence in range(1, 4):
        assert store.read(UUID) == []
        attempt = update(store, now, attempt, sequence, sequence * 5000, complete=sequence == 3)
        assert attempt["nonce"] != first_nonce
    assert store.read(UUID) == [dict(floor="F7", kind="solo_clear", real_ms=15000, ticks=300)]
    assert store.db.execute("SELECT COUNT(*) FROM solo_samples").fetchone()[0] == 3
    with pytest.raises(HTTPException) as error:
        update(store, now, attempt, 4, 20000, complete=True)
    assert error.value.status_code == 409
    assert store.db.execute("SELECT COUNT(*) FROM pb_records").fetchone()[0] == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"nonce": "z" * 43}, "sequence"),
        ({"sequence": 2}, "sequence"),
        ({"elapsed_ms": 30000}, "elapsed_time"),
        ({"elapsed_ms": 0}, "clock"),
        ({"ticks": 5000}, "tick_rate"),
        ({"ticks": 1}, "tick_rate"),
        ({"roster": [UUID, OTHER]}, "not_solo"),
        ({"dead": True}, "death"),
        ({"evidence": {**LOW, "deaths": 1}}, "death"),
        ({"complete": True, "evidence": HIGH}, "incomplete_score"),
    ],
)
def test_invalid_attempt_cannot_be_repaired_into_a_qualifying_pb(storage, change, reason):
    store, now = storage
    attempt = start(store)
    result = update(store, now, attempt, 1, 5000, **change)
    assert result == {"version": 2, "status": "rejected", "reason": reason}
    assert store.read(UUID) == []
    assert store.db.execute("SELECT reason FROM solo_attempts").fetchone()[0] == reason
    with pytest.raises(HTTPException):
        update(store, now, attempt, 1, 10000)


def test_outage_stops_qualification_and_cannot_upload_delayed_timeline(storage):
    store, now = storage
    attempt = start(store)
    now[0] += 16
    assert update(store, now, attempt, 1, 21000)["reason"] == "connection_lost"
    assert store.read(UUID) == []


def test_attempt_is_account_bound(storage):
    store, _ = storage
    attempt = start(store)
    body = SoloProgress(
        version=2,
        attempt_id=attempt["attempt_id"],
        nonce=attempt["nonce"],
        sequence=1,
        elapsed_ms=5000,
        ticks=100,
        roster=[OTHER],
        dead=False,
        valid=True,
        evidence=ScoreEvidence(**LOW),
        complete=False,
    )
    with pytest.raises(HTTPException) as error:
        store.progress(OTHER, body)
    assert error.value.status_code == 404


def report(now, account=UUID, timing=40000, report_id=None, **changes):
    return TerminalReport.model_validate(
        dict(
            version=2,
            report_id=report_id or account,
            floor="F7",
            run_started_ms=int((now[0] - 300) * 1000),
            roster=[UUID, OTHER],
            real_ms=timing,
            ticks=timing // 50,
            **changes,
        )
    )


def test_terminal_single_is_eligible_matching_clients_corroborate_and_replay_is_idempotent(storage):
    store, now = storage
    first = report(now)
    assert store.terminal(UUID, first)["corroboration"] == "single_report"
    assert store.read(UUID)[0]["real_ms"] == 40000
    assert store.terminal(OTHER, report(now, OTHER, 40500))["corroboration"] == "corroborated"
    assert store.terminal(UUID, first)["corroboration"] == "corroborated"
    assert store.db.execute("SELECT COUNT(*) FROM pb_records").fetchone()[0] == 2
    duplicate = report(now, report_id="c" * 32)
    with pytest.raises(HTTPException):
        store.terminal(UUID, duplicate)


def test_retained_terminal_evidence_cannot_recreate_a_deleted_summary(storage):
    store, now = storage
    payload = report(now)
    store.terminal(UUID, payload)
    store.terminal(OTHER, report(now, OTHER, 40500))
    with store.lock, store.db:
        store.db.execute("DELETE FROM pb_records WHERE uuid=?", (UUID,))
    assert store.terminal(UUID, payload) == {
        "version": 2,
        "status": "rejected",
        "reason": "record_deleted",
    }
    assert store.read(UUID) == []


def test_terminal_conflict_flags_both_without_allowing_a_hostile_witness_to_erase_bests(storage):
    store, now = storage
    store.terminal(UUID, report(now))
    assert (
        store.terminal(OTHER, report(now, OTHER, 60000))["corroboration"] == "conflicting_reports"
    )
    assert store.read(UUID)[0]["real_ms"] == 40000
    assert (
        store.db.execute("SELECT DISTINCT source FROM pb_records").fetchone()[0]
        == "conflicting_reports"
    )


def test_cleanup_erases_detail_but_keeps_summary_and_honors_case_holds(storage):
    store, now = storage
    accepted = finish(store, now)
    rejected = start(store)
    update(store, now, rejected, 1, 5000, dead=True)
    now[0] += 8 * DAY
    store.cleanup()
    assert store.db.execute("SELECT COUNT(*) FROM solo_attempts").fetchone()[0] == 1
    with store.db:
        store.db.execute(
            "INSERT INTO evidence_holds VALUES (?,?,NULL)", (accepted["attempt_id"], "case")
        )
    now[0] += 31 * DAY
    store.cleanup()
    assert store.db.execute("SELECT COUNT(*) FROM solo_samples").fetchone()[0] == 3
    with store.db:
        store.db.execute("UPDATE evidence_holds SET until=?", (now[0],))
    store.cleanup()
    assert store.db.execute("SELECT COUNT(*) FROM solo_samples").fetchone()[0] == 0
    assert store.read(UUID)[0]["real_ms"] == 15000


def test_short_sanction_expiry_overrides_default_detail_retention(storage):
    store, now = storage
    accepted = finish(store, now)
    with store.db:
        store.db.execute(
            "INSERT INTO evidence_holds VALUES (?,?,?)",
            (accepted["attempt_id"], "short-ban", now[0] + DAY),
        )
    now[0] += DAY
    store.cleanup()
    assert store.db.execute("SELECT COUNT(*) FROM solo_samples").fetchone()[0] == 0
    assert store.read(UUID)[0]["real_ms"] == 15000


def test_restart_abandons_live_attempt_and_preserves_pb(tmp_path):
    path = tmp_path / "records.db"
    now = [1000.0]
    store = RecordStore(path, clock=lambda: now[0])
    finish(store, now)
    start(store)
    store.close()
    store = RecordStore(path, clock=lambda: now[0])
    assert (
        store.db.execute("SELECT reason FROM solo_attempts WHERE status='abandoned'").fetchone()[0]
        == "service_restart"
    )
    assert store.read(UUID)[0]["real_ms"] == 15000
    store.close()


def test_existing_minima_migrate_once_and_deletion_cannot_reimport_them(tmp_path):
    path = tmp_path / "records.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE mod_bests(uuid TEXT,floor TEXT,kind TEXT,real_ms INTEGER,ticks INTEGER)"
    )
    db.execute("INSERT INTO mod_bests VALUES (?, 'M7', 'solo_clear', 100, 1)", (UUID,))
    db.commit()
    db.close()
    store = RecordStore(path)
    assert store.read(UUID)[0]["real_ms"] == 100
    with store.db:
        store.db.execute("DELETE FROM pb_records WHERE uuid=?", (UUID,))
    store.close()
    store = RecordStore(path)
    assert store.read(UUID) == []
    store.close()


def progress_body(attempt, sequence, *, complete=False):
    return SoloProgress(
        version=2,
        attempt_id=attempt["attempt_id"],
        nonce=attempt["nonce"],
        sequence=sequence,
        elapsed_ms=sequence * 5000,
        ticks=sequence * 100,
        roster=[UUID],
        dead=False,
        valid=True,
        evidence=ScoreEvidence(**(HIGH if complete else LOW)),
        complete=complete,
    )


def test_lost_progress_and_finish_replies_are_recovered_without_duplicate_writes(storage):
    store, now = storage
    attempt = start(store)
    for seq in range(1, 4):
        body = progress_body(attempt, seq, complete=seq == 3)
        now[0] += 5
        attempt = store.progress(UUID, body)
        received = store.db.execute("SELECT last_received FROM solo_attempts").fetchone()[0]
        now[0] += 0.5
        assert store.progress(UUID, body) == attempt
        assert store.db.execute("SELECT last_received FROM solo_attempts").fetchone()[0] == received
        assert store.db.execute("SELECT COUNT(*) FROM solo_samples").fetchone()[0] == seq
    assert store.db.execute("SELECT COUNT(*) FROM pb_records").fetchone()[0] == 1
    assert attempt["status"] == "accepted"


@pytest.mark.parametrize(
    "change",
    [
        {"ticks": 99},
        {"nonce": "x" * 43},
        {"elapsed_ms": 5001},
        {
            "map": {
                "version": 1,
                "rooms": [
                    {
                        "tiles": [0],
                        "type": "NORMAL",
                        "state": "COMPLETE",
                        "name": "Synthetic",
                        "secrets_found": 1,
                        "secrets_total": 1,
                    }
                ],
                "doors": [],
            }
        },
    ],
)
def test_retry_cannot_change_any_progress_field(storage, change):
    store, now = storage
    attempt = start(store)
    for seq in range(1, 4):
        body = progress_body(attempt, seq, complete=seq == 3)
        now[0] += 5
        attempt = store.progress(UUID, body)
    changed = SoloProgress.model_validate({**body.model_dump(), **change})
    with pytest.raises(HTTPException) as error:
        store.progress(UUID, changed)
    assert error.value.status_code == 409
    assert store.db.execute("SELECT COUNT(*) FROM pb_records").fetchone()[0] == 1


@pytest.mark.parametrize("mode", ["expired", "legacy", "missing", "older"])
def test_retry_cannot_refresh_expired_or_unrecognized_evidence(storage, mode):
    store, now = storage
    body = progress_body(start(store), 1)
    now[0] += 5
    reply = store.progress(UUID, body)
    if mode == "expired":
        now[0] += 15.001
    elif mode == "older":
        now[0] += 5
        store.progress(UUID, progress_body(reply, 2))
    else:
        with store.db:
            if mode == "missing":
                store.db.execute("DELETE FROM solo_samples")
            else:
                saved = json.loads(store.db.execute("SELECT body FROM solo_samples").fetchone()[0])
                saved.pop("request_hash")
                store.db.execute("UPDATE solo_samples SET body=?", (json.dumps(saved),))
    assert store.progress(UUID, body)["status"] == "rejected"
    assert store.read(UUID) == []


@pytest.mark.parametrize("deleted", [False, True])
def test_finish_retry_cannot_restore_moderated_or_deleted_records(storage, deleted):
    store, now = storage
    attempt = start(store)
    for seq in range(1, 4):
        body = progress_body(attempt, seq, complete=seq == 3)
        now[0] += 5
        attempt = store.progress(UUID, body)
    with store.db:
        store.db.execute(
            "DELETE FROM pb_records" if deleted else "UPDATE pb_records SET status='invalidated'"
        )
    assert store.progress(UUID, body) == {
        "version": 2,
        "status": "rejected",
        "reason": "record_unavailable",
    }
    assert store.read(UUID) == []
