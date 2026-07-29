"""src.patterns.supervisor 的单元测试。

测试覆盖:
- _parse_json_output: 正常解析 / 容错提取 / 非法 JSON / 非 dict
- _worker: 正常调用 / 带 feedback 调用
- _supervisor: 正常审核
- supervisor: 首轮通过 / 多轮重做通过 / 超时强制返回 / 参数校验
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.patterns.supervisor import (
    _get_session,
    _parse_json_output,
    _supervisor,
    _worker,
    supervisor,
)

# ---------------------------------------------------------------------------
# _parse_json_output
# ---------------------------------------------------------------------------


class TestParseJsonOutput:
    """JSON 解析测试。"""

    def test_parse_valid_json(self) -> None:
        raw = '{"passed": true, "score": 8, "feedback": "good"}'
        result = _parse_json_output(raw, "Supervisor")
        assert result["passed"] is True
        assert result["score"] == 8

    def test_parse_json_with_surrounding_text(self) -> None:
        raw = '以下是审核结果：\n{"passed": false, "score": 5, "feedback": "bad"}\n结束'
        result = _parse_json_output(raw, "Supervisor")
        assert result["passed"] is False
        assert result["score"] == 5

    def test_parse_json_with_markdown_fence(self) -> None:
        raw = '```json\n{"title": "test", "summary": "hi"}\n```'
        result = _parse_json_output(raw, "Worker")
        assert result["title"] == "test"

    def test_parse_invalid_json_raises(self) -> None:
        raw = "这不是JSON"
        with pytest.raises(ValueError, match="Supervisor"):
            _parse_json_output(raw, "Supervisor")

    def test_parse_non_dict_raises(self) -> None:
        raw = "[1, 2, 3]"
        with pytest.raises(ValueError, match="dict"):
            _parse_json_output(raw, "Worker")

    def test_parse_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Supervisor"):
            _parse_json_output("", "Supervisor")


# ---------------------------------------------------------------------------
# _worker
# ---------------------------------------------------------------------------


class TestWorker:
    """Worker Agent 测试。"""

    @patch("src.patterns.supervisor.quick_chat")
    @patch("src.patterns.supervisor._parse_json_output")
    def test_worker_basic(
        self, mock_parse: MagicMock, mock_chat: MagicMock
    ) -> None:
        mock_chat.return_value = '{"title": "分析"}'
        mock_parse.return_value = {"title": "分析"}
        mock_session = MagicMock()

        result = _worker("分析 RAG", mock_session)
        assert result == {"title": "分析"}
        mock_chat.assert_called_once()

    @patch("src.patterns.supervisor.quick_chat")
    @patch("src.patterns.supervisor._parse_json_output")
    def test_worker_with_feedback(
        self, mock_parse: MagicMock, mock_chat: MagicMock
    ) -> None:
        mock_chat.return_value = '{"title": "改进版"}'
        mock_parse.return_value = {"title": "改进版"}
        mock_session = MagicMock()

        _worker("分析 RAG", mock_session, feedback="需要更深入")

        call_args = mock_chat.call_args
        prompt = call_args[0][0]
        assert "需要更深入" in prompt
        assert "分析 RAG" in prompt


# ---------------------------------------------------------------------------
# _supervisor
# ---------------------------------------------------------------------------


class TestSupervisor:
    """Supervisor Agent 测试。"""

    @patch("src.patterns.supervisor.quick_chat")
    @patch("src.patterns.supervisor._parse_json_output")
    def test_supervisor_basic(
        self, mock_parse: MagicMock, mock_chat: MagicMock
    ) -> None:
        mock_chat.return_value = '{"passed": true, "score": 8}'
        mock_parse.return_value = {"passed": True, "score": 8, "feedback": ""}
        mock_session = MagicMock()

        worker_output = {"title": "test", "summary": "summary"}
        result = _supervisor("任务", worker_output, mock_session)

        assert result["passed"] is True
        assert result["score"] == 8

        call_args = mock_chat.call_args
        prompt = call_args[0][0]
        assert "任务" in prompt
        assert json.dumps(worker_output, ensure_ascii=False) in prompt


# ---------------------------------------------------------------------------
# supervisor（集成循环逻辑）
# ---------------------------------------------------------------------------


class TestSupervisorLoop:
    """Supervisor 审核循环测试。"""

    @patch("src.patterns.supervisor._get_session")
    @patch("src.patterns.supervisor._supervisor")
    @patch("src.patterns.supervisor._worker")
    def test_pass_on_first_attempt(
        self,
        mock_worker: MagicMock,
        mock_supervisor: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value = MagicMock()
        mock_worker.return_value = {"title": "报告", "summary": "摘要"}
        mock_supervisor.return_value = {
            "passed": True,
            "score": 9,
            "feedback": "优秀",
        }

        result = supervisor("任务")

        assert result["output"] == {"title": "报告", "summary": "摘要"}
        assert result["attempts"] == 1
        assert result["final_score"] == 9
        assert result["passed"] is True
        assert "warning" not in result
        mock_worker.assert_called_once()

    @patch("src.patterns.supervisor._get_session")
    @patch("src.patterns.supervisor._supervisor")
    @patch("src.patterns.supervisor._worker")
    def test_pass_on_second_attempt(
        self,
        mock_worker: MagicMock,
        mock_supervisor: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value = MagicMock()
        mock_worker.side_effect = [
            {"title": "初稿"},
            {"title": "改进稿"},
        ]
        mock_supervisor.side_effect = [
            {"passed": False, "score": 4, "feedback": "太浅"},
            {"passed": True, "score": 8, "feedback": "通过"},
        ]

        result = supervisor("任务", max_retries=3)

        assert result["attempts"] == 2
        assert result["final_score"] == 8
        assert result["passed"] is True
        assert "warning" not in result
        assert mock_worker.call_count == 2

        # 验证第二次 worker 调用收到 feedback
        second_call_kwargs = mock_worker.call_args_list[1].kwargs
        assert second_call_kwargs["feedback"] == "太浅"

    @patch("src.patterns.supervisor._get_session")
    @patch("src.patterns.supervisor._supervisor")
    @patch("src.patterns.supervisor._worker")
    def test_force_return_after_max_retries(
        self,
        mock_worker: MagicMock,
        mock_supervisor: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value = MagicMock()
        mock_worker.return_value = {"title": "始终不达标"}
        mock_supervisor.return_value = {
            "passed": False,
            "score": 3,
            "feedback": "不达标",
        }

        result = supervisor("任务", max_retries=2)

        assert result["attempts"] == 2
        assert result["final_score"] == 3
        assert result["passed"] is False
        assert "warning" in result
        assert "2" in result["warning"]
        assert mock_worker.call_count == 2

    @patch("src.patterns.supervisor._get_session")
    @patch("src.patterns.supervisor._supervisor")
    @patch("src.patterns.supervisor._worker")
    def test_score_threshold_passes_without_passed_flag(
        self,
        mock_worker: MagicMock,
        mock_supervisor: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """score >= 7 但 passed=false 时也应通过。"""
        mock_session.return_value = MagicMock()
        mock_worker.return_value = {"title": "报告"}
        mock_supervisor.return_value = {
            "passed": False,
            "score": 7,
            "feedback": "勉强通过",
        }

        result = supervisor("任务")

        assert result["passed"] is True
        assert result["final_score"] == 7
        assert result["attempts"] == 1

    @patch("src.patterns.supervisor._get_session")
    @patch("src.patterns.supervisor._supervisor")
    @patch("src.patterns.supervisor._worker")
    def test_session_closed_after_run(
        self,
        mock_worker: MagicMock,
        mock_supervisor: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_sess = MagicMock()
        mock_session.return_value = mock_sess
        mock_worker.return_value = {"title": "报告"}
        mock_supervisor.return_value = {
            "passed": True,
            "score": 9,
            "feedback": "",
        }

        supervisor("任务")
        mock_sess.close.assert_called_once()

    @patch("src.patterns.supervisor._get_session")
    def test_no_session_raises_runtime_error(
        self, mock_session: MagicMock
    ) -> None:
        mock_session.return_value = None
        with pytest.raises(RuntimeError, match="数据库会话"):
            supervisor("任务")

    def test_invalid_max_retries(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            supervisor("任务", max_retries=0)

        with pytest.raises(ValueError, match="max_retries"):
            supervisor("任务", max_retries=11)


# ---------------------------------------------------------------------------
# _get_session
# ---------------------------------------------------------------------------


class TestGetSession:
    """数据库会话获取测试。"""

    def test_get_session_success(self) -> None:
        mock_factory = MagicMock()
        mock_session = MagicMock()
        mock_factory.return_value = mock_session
        with patch(
            "src.config.database.get_session_factory",
            return_value=mock_factory,
        ):
            result = _get_session()
        assert result is mock_session

    def test_get_session_failure_returns_none(self) -> None:
        with patch(
            "src.config.database.get_session_factory",
            side_effect=Exception("DB unavailable"),
        ):
            result = _get_session()
        assert result is None
