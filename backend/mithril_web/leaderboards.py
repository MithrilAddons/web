"""Discord rankings of eligible mod PBs, read under the record/erasure lock."""

from fastapi import HTTPException

CATEGORIES = (
    ("f7_solo", "F7", "solo_clear"),
    ("m7_solo", "M7", "solo_clear"),
    ("m7_terminals", "M7", "terminals"),
)


def snapshot(records, auth):
    with records.lock, auth.lock, records.db:
        # Only authenticated identities may name a record. Pending proof/link names
        # are user input and must never enter a public leaderboard.
        records.db.execute(
            """
            INSERT OR IGNORE INTO record_names (uuid,name)
            SELECT uuid,name FROM (
                SELECT uuid,name,ROW_NUMBER() OVER (
                    PARTITION BY uuid ORDER BY expires DESC,token) AS choice
                FROM accounts.auth WHERE kind IN ('session','device','sync','party')
                    AND expires>?
            ) WHERE choice=1 AND uuid IN (SELECT uuid FROM pb_records)
        """,
            (records.clock(),),
        )
        boards = {}
        for key, floor, kind in CATEGORIES:
            # Both clocks must come from the same observation. Terminal ties share
            # a dense rank only when both elapsed time and the tick tiebreaker match.
            ordering = "real_ms,ticks" if kind == "terminals" else "ticks"
            ranking = "DENSE_RANK()" if kind == "terminals" else "ROW_NUMBER()"
            rank_order = ordering if kind == "terminals" else "ticks,uuid"
            rows = records.db.execute(
                f"""
                WITH best AS (
                    SELECT *,ROW_NUMBER() OVER (
                        PARTITION BY uuid ORDER BY {ordering},created,id) AS choice
                    FROM pb_records p WHERE status='eligible' AND floor=? AND kind=?
                    AND NOT EXISTS (SELECT 1 FROM sanctions s WHERE s.uuid=p.uuid
                        AND s.kind IN ('ban','network_ban') AND s.revoked IS NULL
                        AND (s.expires IS NULL OR s.expires>?))
                ), ranked AS (
                    SELECT uuid,real_ms,ticks,{ranking} OVER (ORDER BY {rank_order}) AS rank
                    FROM best WHERE choice=1
                ) SELECT r.*,n.name FROM ranked r LEFT JOIN record_names n USING(uuid)
                WHERE rank<=10 ORDER BY rank,uuid LIMIT 1001
            """,
                (floor, kind, records.clock()),
            ).fetchall()
            if len(rows) > 1000:
                raise HTTPException(503, "Leaderboard exceeds publication capacity")
            boards[key] = [dict(row) for row in rows]
        return {"version": 1, "updated_at": records.clock(), "boards": boards}
