"""src.graph.nodes.human_flag_node 模块的单元测试。

测试覆盖：
- 正常写入 flagged 文件（JSON 结构 / 文件名 / 内容校验）
- 空 analyses 也写入（不跳过，记录原始状态）
- 不污染 knowledge/articles/ 目录
- 文件名包含 trace_id 和时间戳
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

from src.graph.nodes import human_flag_node


class TestHumanFlagNode:
    """human_flag_node 测试。"""

    def test_writes_flagged_file(self) -> None:
        """正常写入 flagged JSON 文件。"""
        analyses = [
            {"title": "问题条目A", "summary": "质量差", "score": 0.3},
            {"title": "问题条目B", "summary": "不相关", "score": 0.2},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                result = human_flag_node({
                    "analyses": analyses,
                    "iteration": 3,
                    "review_feedback": "审核循环达上限, 需人工判断",
                    "trace_id": "abc123",
                })

            assert result["human_flagged"] is True

            files = os.listdir(flagged_dir)
            assert len(files) == 1
            assert files[0].startswith("flagged-abc123-")

            with open(os.path.join(flagged_dir, files[0]), encoding="utf-8") as f:
                record = json.load(f)

            assert record["trace_id"] == "abc123"
            assert record["iteration"] == 3
            assert record["review_feedback"] == "审核循环达上限, 需人工判断"
            assert len(record["analyses"]) == 2
            assert record["analyses"][0]["title"] == "问题条目A"
            assert "flagged_at" in record

    def test_empty_analyses_still_writes(self) -> None:
        """空 analyses 也写入文件（记录原始状态）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                result = human_flag_node({
                    "analyses": [],
                    "iteration": 3,
                    "review_feedback": "无条目但审核未通过",
                    "trace_id": "empty-case",
                })

            assert result["human_flagged"] is True

            files = os.listdir(flagged_dir)
            assert len(files) == 1

            with open(os.path.join(flagged_dir, files[0]), encoding="utf-8") as f:
                record = json.load(f)
            assert record["analyses"] == []

    def test_filename_contains_trace_id(self) -> None:
        """文件名包含 trace_id。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                human_flag_node({
                    "analyses": [{"title": "a"}],
                    "iteration": 3,
                    "review_feedback": "feedback",
                    "trace_id": "trace-xyz-789",
                })

            files = os.listdir(flagged_dir)
            assert len(files) == 1
            assert "trace-xyz-789" in files[0]

    def test_no_trace_id_uses_placeholder(self) -> None:
        """无 trace_id 时文件名使用占位符。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                human_flag_node({
                    "analyses": [{"title": "a"}],
                    "iteration": 3,
                    "review_feedback": "feedback",
                })

            files = os.listdir(flagged_dir)
            assert len(files) == 1
            assert "no-trace" in files[0]

    def test_trace_id_with_slash_sanitized(self) -> None:
        """trace_id 中的斜杠被替换，避免路径穿越。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                human_flag_node({
                    "analyses": [{"title": "a"}],
                    "iteration": 3,
                    "review_feedback": "feedback",
                    "trace_id": "evil/../../../etc",
                })

            files = os.listdir(flagged_dir)
            assert len(files) == 1
            # 斜杠被替换为连字符，不会产生子目录
            assert "/" not in files[0]

    def test_does_not_pollute_articles_dir(self) -> None:
        """flagged 文件不写入 knowledge/articles/ 目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            articles_dir = os.path.join(tmpdir, "articles")
            os.makedirs(articles_dir)

            with (
                patch("src.graph.nodes._FLAGGED_DIR", flagged_dir),
                patch("src.graph.nodes._ARTICLES_DIR", articles_dir),
            ):
                human_flag_node({
                    "analyses": [{"title": "a"}],
                    "iteration": 3,
                    "review_feedback": "feedback",
                    "trace_id": "test123",
                })

            # flagged 目录有文件
            assert len(os.listdir(flagged_dir)) == 1
            # articles 目录无新增文件
            assert len(os.listdir(articles_dir)) == 0

    def test_multiple_calls_create_distinct_files(self) -> None:
        """多次调用生成不同文件名（时间戳不同）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                human_flag_node({
                    "analyses": [{"title": "a"}],
                    "iteration": 3,
                    "review_feedback": "f1",
                    "trace_id": "t1",
                })
                # 手动等待以确保时间戳不同
                import time

                time.sleep(1.1)
                human_flag_node({
                    "analyses": [{"title": "b"}],
                    "iteration": 3,
                    "review_feedback": "f2",
                    "trace_id": "t2",
                })

            files = os.listdir(flagged_dir)
            assert len(files) == 2

    def test_flag_record_structure(self) -> None:
        """flagged JSON 记录包含所有必需字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            flagged_dir = os.path.join(tmpdir, "flagged")
            with patch("src.graph.nodes._FLAGGED_DIR", flagged_dir):
                human_flag_node({
                    "analyses": [{"title": "a", "score": 0.4}],
                    "iteration": 3,
                    "review_feedback": "需要人工判断",
                    "trace_id": "struct-test",
                })

            files = os.listdir(flagged_dir)
            with open(os.path.join(flagged_dir, files[0]), encoding="utf-8") as f:
                record = json.load(f)

            required_keys = {"trace_id", "flagged_at", "iteration", "review_feedback", "analyses"}
            assert required_keys.issubset(record.keys())
