"""src.main 的单元测试。

测试覆盖：
- main 参数解析
- --stage 各选项
- --log-level 各选项
- main 返回值
"""

from __future__ import annotations

import pytest

from src.main import main


class TestMain:
    """main CLI 入口测试。"""

    def test_default_stage_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """默认 stage=all 执行全流程，返回 0。"""
        monkeypatch.setattr("sys.argv", ["main"])
        ret = main()
        assert ret == 0

    def test_stage_collect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--stage collect 返回 0。"""
        monkeypatch.setattr("sys.argv", ["main", "--stage", "collect"])
        ret = main()
        assert ret == 0

    def test_stage_analyze(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--stage analyze 返回 0。"""
        monkeypatch.setattr("sys.argv", ["main", "--stage", "analyze"])
        ret = main()
        assert ret == 0

    def test_stage_curate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--stage curate 返回 0。"""
        monkeypatch.setattr("sys.argv", ["main", "--stage", "curate"])
        ret = main()
        assert ret == 0

    def test_log_level_debug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--log-level DEBUG 不报错。"""
        monkeypatch.setattr("sys.argv", ["main", "--log-level", "DEBUG"])
        ret = main()
        assert ret == 0

    def test_log_level_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--log-level ERROR 不报错。"""
        monkeypatch.setattr("sys.argv", ["main", "--log-level", "ERROR"])
        ret = main()
        assert ret == 0

    def test_invalid_stage_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无效 stage 值退出。"""
        monkeypatch.setattr("sys.argv", ["main", "--stage", "invalid"])
        with pytest.raises(SystemExit):
            main()
