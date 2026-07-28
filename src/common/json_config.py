"""全局 JSON 时间序列化配置。

类似 Spring Boot 中 Jackson 的 ``ObjectMapper`` 全局配置，
统一所有 JSON 序列化路径中 ``datetime`` / ``date`` 的输出格式。

统一格式约定：
    - ``datetime`` -> ``yyyy-MM-dd'T'HH:mm:ss``（naive）
                       ``yyyy-MM-dd'T'HH:mm:ssZ``（UTC tz-aware）
    - ``date``     -> ``yyyy-MM-dd``

核心设计：通过 Pydantic v2 的 ``Annotated + PlainSerializer`` 类型别名
（:data:`JsonDateTime` / :data:`JsonDate`），在 Pydantic 模型字段声明处
指定序列化行为。这覆盖了所有 Pydantic 序列化路径：

    - ``model_dump()``
    - ``model_dump(mode="json")``
    - ``model_dump_json()``
    - FastAPI ``jsonable_encoder()``（``response_model`` 自动序列化）

对于非 Pydantic 路径（手动构造 ``JSONResponse(content=dict_with_datetime)``），
提供 :class:`CustomJSONEncoder` + :class:`CustomJSONResponse` 兜底。

使用方式：
    1. 在 Pydantic schema 中使用 ``JsonDateTime`` 替代 ``datetime``::

        from src.common.json_config import JsonDateTime

        class MyResponse(BaseModel):
            created_at: JsonDateTime

    2. FastAPI 应用注册默认响应类::

        from src.common.json_config import CustomJSONResponse

        app = FastAPI(default_response_class=CustomJSONResponse)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi.responses import JSONResponse
from pydantic import PlainSerializer

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATETIME_FORMAT_UTC = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT = "%Y-%m-%d"


def format_datetime(dt: datetime) -> str:
    """将 datetime 序列化为 ISO 8601 字符串。

    naive datetime（无时区）输出 ``yyyy-MM-dd'T'HH:mm:ss``；
    tz-aware datetime 统一转换为 UTC 后输出 ``yyyy-MM-dd'T'HH:mm:ssZ``。

    Args:
        dt: 待格式化的 datetime 对象。

    Returns:
        ISO 8601 格式的时间字符串。
    """
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).strftime(DATETIME_FORMAT_UTC)
    return dt.strftime(DATETIME_FORMAT)


def format_date(d: date) -> str:
    """将 date 序列化为 ``yyyy-MM-dd`` 字符串。

    Args:
        d: 待格式化的 date 对象。

    Returns:
        ``yyyy-MM-dd`` 格式的日期字符串。
    """
    return d.strftime(DATE_FORMAT)


JsonDateTime = Annotated[datetime, PlainSerializer(format_datetime, return_type=str)]
"""Pydantic datetime 类型别名，序列化时统一输出 ``yyyy-MM-dd'T'HH:mm:ss``。

naive datetime 输出无后缀格式；tz-aware datetime 转换为 UTC 后追加 ``Z``。
在所有 Pydantic 序列化路径（``model_dump()`` / ``model_dump_json()`` /
``jsonable_encoder()``）中均生效。
"""

JsonDate = Annotated[date, PlainSerializer(format_date, return_type=str)]
"""Pydantic date 类型别名，序列化时统一输出 ``yyyy-MM-dd``。"""


class CustomJSONEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，处理 datetime / date 类型。

    被用于 :class:`CustomJSONResponse`，确保通过 ``JSONResponse(content=...)``
    手动返回的响应（content 中含 raw datetime / date 对象）也能正确序列化。
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return format_datetime(o)
        if isinstance(o, date):
            return format_date(o)
        return super().default(o)


class CustomJSONResponse(JSONResponse):
    """使用 :class:`CustomJSONEncoder` 的 JSONResponse。

    替换 FastAPI 默认的 ``JSONResponse``，确保所有 JSON 响应统一序列化 datetime/date。
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            cls=CustomJSONEncoder,
        ).encode("utf-8")


__all__ = [
    "CustomJSONEncoder",
    "CustomJSONResponse",
    "DATE_FORMAT",
    "DATETIME_FORMAT",
    "DATETIME_FORMAT_UTC",
    "JsonDate",
    "JsonDateTime",
    "format_date",
    "format_datetime",
]
