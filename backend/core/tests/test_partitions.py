from datetime import date

import pytest

from hirevion_core.db.partitions import month_ranges, partition_sql


def test_month_ranges_cross_a_year_boundary() -> None:
    assert month_ranges(date(2026, 11, 17), 3) == [
        ("y2026m11", date(2026, 11, 1), date(2026, 12, 1)),
        ("y2026m12", date(2026, 12, 1), date(2027, 1, 1)),
        ("y2027m01", date(2027, 1, 1), date(2027, 2, 1)),
    ]


def test_month_ranges_need_at_least_one_month() -> None:
    with pytest.raises(ValueError, match="months"):
        month_ranges(date(2026, 9, 1), 0)


def test_partition_bounds_are_utc_midnights() -> None:
    assert partition_sql("audit_logs", "y2026m09", date(2026, 9, 1), date(2026, 10, 1)) == (
        "CREATE TABLE audit_logs_y2026m09 PARTITION OF audit_logs "
        "FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00')"
    )


def test_partition_sql_rejects_unsafe_names() -> None:
    with pytest.raises(ValueError, match="identifier"):
        partition_sql("audit_logs; drop", "y2026m09", date(2026, 9, 1), date(2026, 10, 1))
