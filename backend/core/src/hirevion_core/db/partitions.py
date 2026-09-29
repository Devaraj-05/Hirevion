"""Monthly range partitions for the high-volume tables (master plan §7).

`hv migrate` keeps this month's and the next months' partitions in place. Rows outside them
land in the table's DEFAULT partition. Partitions get no grants: the application roles reach
them only through the parent table, whose row-level security then applies.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from hirevion_core.db.rls import identifier

# Tables partitioned BY RANGE (occurred_at), and how many months migrate() creates ahead.
PARTITIONED_TABLES = ("audit_logs", "usage_events")
MONTHS_AHEAD = 3


def month_ranges(start: date, months: int) -> list[tuple[str, date, date]]:
    """`(suffix, first day, first day of the next month)` for `months` months from `start`."""
    if months < 1:
        raise ValueError("months must be at least 1")
    ranges: list[tuple[str, date, date]] = []
    year, month = start.year, start.month
    for _ in range(months):
        lower = date(year, month, 1)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        ranges.append((f"y{lower.year}m{lower.month:02d}", lower, date(year, month, 1)))
    return ranges


def partition_sql(table: str, suffix: str, lower: date, upper: date) -> str:
    """CREATE TABLE for one partition; the bounds are UTC midnights, whatever the session zone."""
    name = identifier(f"{identifier(table)}_{suffix}")
    return (
        f"CREATE TABLE {name} PARTITION OF {table} "
        f"FOR VALUES FROM ('{lower.isoformat()} 00:00:00+00') "
        f"TO ('{upper.isoformat()} 00:00:00+00')"
    )


async def ensure_monthly_partitions(
    conn: AsyncConnection, table: str, start: date, months: int
) -> list[str]:
    """Create the missing monthly partitions of `table`; returns the names it created."""
    created: list[str] = []
    for suffix, lower, upper in month_ranges(start, months):
        name = f"{table}_{suffix}"
        if await conn.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is None:
            await conn.exec_driver_sql(partition_sql(table, suffix, lower, upper))
            created.append(name)
    return created
