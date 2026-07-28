"""src.utils.id_gen 的单元测试。

测试覆盖：
- build_article_id 正常格式
- build_article_id 不同日期
- build_article_id 边界序号（1, 9999）
- build_article_id 超限抛 ValueError
- build_article_id 非正整数抛 ValueError
- build_article_id 类型校验
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.utils.id_gen import build_article_id


class TestBuildArticleId:
    """build_article_id 测试。"""

    def test_basic_format(self) -> None:
        """基本格式 kb-YYYYMMDD-NNNN。"""
        dt = datetime(2026, 7, 27, 8, 0, 0, tzinfo=UTC)
        result = build_article_id(1, dt)
        assert result == "kb-20260727-0001"

    def test_different_date(self) -> None:
        """不同日期生成不同 ID。"""
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = build_article_id(42, dt)
        assert result == "kb-20260101-0042"

    def test_max_sequence(self) -> None:
        """序号 9999 不报错。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        result = build_article_id(9999, dt)
        assert result == "kb-20260727-9999"

    def test_min_sequence(self) -> None:
        """序号 1 零填充至 4 位。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        result = build_article_id(1, dt)
        assert result.endswith("-0001")

    def test_exceeds_max_raises(self) -> None:
        """序号超过 9999 抛 ValueError。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        with pytest.raises(ValueError, match="超过"):
            build_article_id(10000, dt)

    def test_zero_raises(self) -> None:
        """序号 0 抛 ValueError。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        with pytest.raises(ValueError, match="正整数"):
            build_article_id(0, dt)

    def test_negative_raises(self) -> None:
        """负序号抛 ValueError。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        with pytest.raises(ValueError, match="正整数"):
            build_article_id(-1, dt)

    def test_non_int_db_id_raises(self) -> None:
        """db_id 非 int 抛 TypeError。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        with pytest.raises(TypeError, match="int"):
            build_article_id("1", dt)  # type: ignore[arg-type]

    def test_bool_db_id_raises(self) -> None:
        """db_id 为 bool 抛 TypeError（bool 是 int 子类但须排除）。"""
        dt = datetime(2026, 7, 27, tzinfo=UTC)
        with pytest.raises(TypeError, match="int"):
            build_article_id(True, dt)  # type: ignore[arg-type]

    def test_non_datetime_raises(self) -> None:
        """collected_at 非 datetime 抛 TypeError。"""
        with pytest.raises(TypeError, match="datetime"):
            build_article_id(1, "2026-07-27")  # type: ignore[arg-type]

    def test_timezone_conversion(self) -> None:
        """非 UTC 时区的时间转换为 UTC 日期。"""
        # 2026-07-27 01:00:00 UTC+8 == 2026-07-26 17:00:00 UTC
        tz_plus8 = timezone(timedelta(hours=8))
        dt_local = datetime(2026, 7, 27, 1, 0, 0, tzinfo=tz_plus8)
        result = build_article_id(1, dt_local)
        assert result == "kb-20260726-0001"

    def test_naive_datetime_assumed_utc(self) -> None:
        """无时区信息的 datetime 按 UTC 处理。"""
        dt = datetime(2026, 7, 27, 8, 0, 0)
        result = build_article_id(1, dt)
        assert result == "kb-20260727-0001"
