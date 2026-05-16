"""Complex queries including time-bucketed aggregation."""

from typing import Any

from .database import Database


async def get_equity_bucketed(
    db: Database,
    account_id: str,
    currency: str,
    since: int,
    until: int,
    bucket_ms: int = 3_600_000,
) -> list[dict[str, Any]]:
    """Query equity snapshots aggregated into time buckets.

    Each bucket contains AVG, MIN, MAX equity values.

    Args:
        db: Database instance.
        account_id: Account uuid (or legacy env string for v3-era rows).
        currency: Currency (e.g. "BTC").
        since: Start timestamp in milliseconds.
        until: End timestamp in milliseconds.
        bucket_ms: Bucket size in milliseconds (default: 1 hour).

    Returns:
        List of dicts with bucket_time, avg_equity, min_equity, max_equity,
        avg_balance, point_count.
    """
    cursor = await db.connection.execute(
        """SELECT
               (timestamp / ?) * ? AS bucket_time,
               AVG(equity) AS avg_equity,
               MIN(equity) AS min_equity,
               MAX(equity) AS max_equity,
               AVG(balance) AS avg_balance,
               AVG(unrealized_pnl) AS avg_unrealized_pnl,
               AVG(realized_pnl) AS avg_realized_pnl,
               COUNT(*) AS point_count
           FROM equity_snapshots
           WHERE account_id = ? AND currency = ? AND timestamp >= ? AND timestamp <= ?
           GROUP BY bucket_time
           ORDER BY bucket_time ASC""",
        (bucket_ms, bucket_ms, account_id, currency, since, until),
    )
    rows = await cursor.fetchall()
    return [
        {
            "bucket_time": r[0],
            "avg_equity": r[1],
            "min_equity": r[2],
            "max_equity": r[3],
            "avg_balance": r[4],
            "avg_unrealized_pnl": r[5],
            "avg_realized_pnl": r[6],
            "point_count": r[7],
        }
        for r in rows
    ]


def auto_bucket_ms(since: int, until: int, max_points: int = 1000) -> int:
    """Choose a bucket size to keep the result under max_points.

    Returns bucket size in milliseconds.
    """
    span_ms = until - since
    if span_ms <= 0:
        return 60_000  # 1 minute

    # Target roughly max_points buckets
    bucket = span_ms // max_points

    # Snap to a nice interval
    INTERVALS = [
        60_000,        # 1 minute
        300_000,       # 5 minutes
        900_000,       # 15 minutes
        3_600_000,     # 1 hour
        14_400_000,    # 4 hours
        86_400_000,    # 1 day
        604_800_000,   # 1 week
    ]

    for interval in INTERVALS:
        if interval >= bucket:
            return interval

    return INTERVALS[-1]
