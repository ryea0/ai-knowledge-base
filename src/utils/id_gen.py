"""知识条目 article_id 生成工具。

article_id 格式：kb-YYYYMMDD-NNNN
- YYYYMMDD：采集日（UTC）。
- NNNN：DB 自增主键 `id` 的值，零填充至 4 位，全局递增（不按日重置）。
- id > 9999 时报错（4 位上限），扩位改 ``_SEQ_WIDTH`` 常量即可。

取号流程（须在 DB 事务内）：
1. INSERT 行（不含 article_id，或占位）。
2. 取 ``LAST_INSERT_ID()`` 得到 id。
3. ``build_article_id(id, collected_at)`` 生成 article_id。
4. UPDATE 回填 article_id。
5. 提交事务。

并发安全由 InnoDB 自增锁保证，无需额外加锁。
"""

from datetime import UTC, datetime

_SEQ_WIDTH = 4
_MAX_SEQ = 10**_SEQ_WIDTH - 1  # 9999
_PREFIX = "kb"


def build_article_id(db_id: int, collected_at: datetime) -> str:
    """根据 DB 自增主键和采集时间生成 article_id。

    Args:
        db_id: ``kb_article.id`` 自增主键值，须为正整数。
        collected_at: 采集时间，取其 UTC 日期作为 YYYYMMDD 段。

    Returns:
        形如 ``kb-20260727-0001`` 的业务 ID。

    Raises:
        ValueError: db_id 非正或超过 4 位上限。
        TypeError: collected_at 不是 datetime 实例。
    """
    if not isinstance(db_id, int) or isinstance(db_id, bool):
        raise TypeError(f"db_id 必须为 int，实际类型: {type(db_id).__name__}")
    if db_id < 1:
        raise ValueError(f"db_id 必须为正整数，实际: {db_id}")
    if db_id > _MAX_SEQ:
        raise ValueError(
            f"db_id 超过 {_SEQ_WIDTH} 位上限 {_MAX_SEQ}，当前值 {db_id}；"
            f"请扩宽 _SEQ_WIDTH 常量"
        )
    if not isinstance(collected_at, datetime):
        raise TypeError(
            f"collected_at 必须为 datetime，实际类型: {type(collected_at).__name__}"
        )

    date_str = collected_at.astimezone(UTC).strftime("%Y%m%d")
    seq_str = str(db_id).zfill(_SEQ_WIDTH)
    return f"{_PREFIX}-{date_str}-{seq_str}"
