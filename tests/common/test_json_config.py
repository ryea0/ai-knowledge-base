"""src.common.json_config 的单元测试。

测试覆盖：
- format_datetime: naive / tz-aware / 微秒截断
- format_date: 基本格式
- JsonDateTime / JsonDate Pydantic 类型别名: model_dump / model_dump_json / jsonable_encoder
- CustomJSONEncoder: datetime / date 原始对象序列化
- CustomJSONResponse: 含 datetime 的 dict 正确渲染
- 异常处理器路径: model_dump(mode='json') + CustomJSONResponse 不 crash
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from src.common.json_config import (
    CustomJSONEncoder,
    CustomJSONResponse,
    JsonDate,
    JsonDateTime,
    format_date,
    format_datetime,
)


class TestFormatDatetime:
    """format_datetime 函数测试。"""

    def test_naive_datetime(self) -> None:
        """naive datetime 输出无时区后缀。"""
        dt = datetime(2026, 7, 28, 8, 5, 30)
        assert format_datetime(dt) == "2026-07-28T08:05:30"

    def test_naive_datetime_with_microseconds(self) -> None:
        """微秒被截断。"""
        dt = datetime(2026, 7, 28, 8, 5, 30, 123456)
        assert format_datetime(dt) == "2026-07-28T08:05:30"

    def test_utc_datetime(self) -> None:
        """UTC tz-aware datetime 输出 Z 后缀。"""
        dt = datetime(2026, 7, 28, 8, 5, 30, tzinfo=UTC)
        assert format_datetime(dt) == "2026-07-28T08:05:30Z"

    def test_non_utc_timezone(self) -> None:
        """非 UTC 时区转换为 UTC 后输出 Z 后缀。"""
        tz_plus8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 7, 28, 16, 5, 30, tzinfo=tz_plus8)
        assert format_datetime(dt) == "2026-07-28T08:05:30Z"

    def test_utc_with_microseconds(self) -> None:
        """UTC + 微秒截断 + Z 后缀。"""
        dt = datetime(2026, 7, 28, 8, 5, 30, 999000, tzinfo=UTC)
        assert format_datetime(dt) == "2026-07-28T08:05:30Z"


class TestFormatDate:
    """format_date 函数测试。"""

    def test_basic_date(self) -> None:
        """基本日期格式。"""
        d = date(2026, 7, 28)
        assert format_date(d) == "2026-07-28"

    def test_date_from_datetime(self) -> None:
        """从 datetime 提取 date 后格式化。"""
        dt = datetime(2026, 1, 1, 23, 59, 59)
        assert format_date(dt.date()) == "2026-01-01"


class _ModelWithJsonDateTime(BaseModel):
    """测试用 Pydantic 模型，含 JsonDateTime / JsonDate 字段。"""

    created_at: JsonDateTime
    updated_at: JsonDateTime | None = None
    birthday: JsonDate | None = None
    name: str = "test"


class TestJsonDateTimeAnnotated:
    """JsonDateTime / JsonDate Annotated 类型别名测试。"""

    def test_model_dump_naive(self) -> None:
        """model_dump 返回格式化字符串（naive）。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30, 123000))
        dumped = m.model_dump()
        assert dumped["created_at"] == "2026-07-28T08:05:30"

    def test_model_dump_utc(self) -> None:
        """model_dump 返回格式化字符串（UTC Z 后缀）。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30, tzinfo=UTC))
        dumped = m.model_dump()
        assert dumped["created_at"] == "2026-07-28T08:05:30Z"

    def test_model_dump_json(self) -> None:
        """model_dump_json 返回正确格式。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30))
        j = json.loads(m.model_dump_json())
        assert j["created_at"] == "2026-07-28T08:05:30"

    def test_model_dump_mode_json(self) -> None:
        """model_dump(mode='json') 返回格式化字符串。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30, 999000))
        dumped = m.model_dump(mode="json")
        assert dumped["created_at"] == "2026-07-28T08:05:30"

    def test_jsonable_encoder(self) -> None:
        """jsonable_encoder（FastAPI response_model 路径）返回格式化字符串。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30, 123000))
        encoded = jsonable_encoder(m)
        assert encoded["created_at"] == "2026-07-28T08:05:30"

    def test_optional_none(self) -> None:
        """Optional 字段为 None 时正确处理。"""
        m = _ModelWithJsonDateTime(created_at=datetime(2026, 7, 28, 8, 5, 30))
        dumped = m.model_dump()
        assert dumped["updated_at"] is None
        assert dumped["birthday"] is None

    def test_date_field(self) -> None:
        """JsonDate 字段正确序列化。"""
        m = _ModelWithJsonDateTime(
            created_at=datetime(2026, 7, 28, 8, 5, 30),
            birthday=date(2026, 7, 28),
        )
        dumped = m.model_dump()
        assert dumped["birthday"] == "2026-07-28"

    def test_all_paths_consistent(self) -> None:
        """三种序列化路径输出一致。"""
        dt = datetime(2026, 7, 28, 8, 5, 30, 123000, tzinfo=UTC)
        m = _ModelWithJsonDateTime(created_at=dt)
        expected = "2026-07-28T08:05:30Z"
        assert m.model_dump()["created_at"] == expected
        assert m.model_dump(mode="json")["created_at"] == expected
        assert json.loads(m.model_dump_json())["created_at"] == expected
        assert jsonable_encoder(m)["created_at"] == expected


class TestCustomJSONEncoder:
    """CustomJSONEncoder 测试。"""

    def test_encode_naive_datetime(self) -> None:
        """编码 naive datetime。"""
        data: dict[str, Any] = {"dt": datetime(2026, 7, 28, 8, 5, 30, 123000)}
        result = json.dumps(data, cls=CustomJSONEncoder)
        assert json.loads(result)["dt"] == "2026-07-28T08:05:30"

    def test_encode_utc_datetime(self) -> None:
        """编码 UTC datetime。"""
        data: dict[str, Any] = {"dt": datetime(2026, 7, 28, 8, 5, 30, tzinfo=UTC)}
        result = json.dumps(data, cls=CustomJSONEncoder)
        assert json.loads(result)["dt"] == "2026-07-28T08:05:30Z"

    def test_encode_date(self) -> None:
        """编码 date。"""
        data: dict[str, Any] = {"d": date(2026, 7, 28)}
        result = json.dumps(data, cls=CustomJSONEncoder)
        assert json.loads(result)["d"] == "2026-07-28"

    def test_encode_none(self) -> None:
        """None 值正常编码。"""
        data: dict[str, Any] = {"dt": None}
        result = json.dumps(data, cls=CustomJSONEncoder)
        assert json.loads(result)["dt"] is None

    def test_encode_mixed(self) -> None:
        """混合类型编码。"""
        data: dict[str, Any] = {
            "name": "test",
            "created_at": datetime(2026, 7, 28, 8, 5, 30),
            "birthday": date(2026, 7, 28),
            "count": 42,
            "active": True,
        }
        result = json.dumps(data, cls=CustomJSONEncoder)
        parsed = json.loads(result)
        assert parsed["created_at"] == "2026-07-28T08:05:30"
        assert parsed["birthday"] == "2026-07-28"
        assert parsed["count"] == 42
        assert parsed["active"] is True


class TestCustomJSONResponse:
    """CustomJSONResponse 测试。"""

    def test_render_raw_datetime(self) -> None:
        """渲染含 raw datetime 对象的 content。"""
        content: dict[str, Any] = {
            "code": 0,
            "data": {"created_at": datetime(2026, 7, 28, 8, 5, 30, 123000)},
        }
        resp = CustomJSONResponse(content=content)
        body = json.loads(resp.body)
        assert body["data"]["created_at"] == "2026-07-28T08:05:30"

    def test_render_raw_date(self) -> None:
        """渲染含 raw date 对象的 content。"""
        content: dict[str, Any] = {"birthday": date(2026, 7, 28)}
        resp = CustomJSONResponse(content=content)
        body = json.loads(resp.body)
        assert body["birthday"] == "2026-07-28"

    def test_render_no_datetime(self) -> None:
        """无 datetime 的 content 正常渲染。"""
        content: dict[str, Any] = {"code": 0, "message": "ok"}
        resp = CustomJSONResponse(content=content)
        body = json.loads(resp.body)
        assert body == content

    def test_render_utc_datetime(self) -> None:
        """渲染 UTC datetime。"""
        content: dict[str, Any] = {"dt": datetime(2026, 7, 28, 8, 5, 30, tzinfo=UTC)}
        resp = CustomJSONResponse(content=content)
        body = json.loads(resp.body)
        assert body["dt"] == "2026-07-28T08:05:30Z"

    def test_status_code(self) -> None:
        """自定义 status_code 正确设置。"""
        resp = CustomJSONResponse(content={"msg": "err"}, status_code=503)
        assert resp.status_code == 503
