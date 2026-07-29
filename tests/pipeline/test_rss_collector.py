"""src.pipeline.rss_collector 的单元测试。

测试覆盖：
- RSS XML 解析（RSS 2.0 / Atom）
- YAML 配置加载
- CDATA 清理
- 链接提取（RSS vs Atom）
- 重试逻辑
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.pipeline.rss_collector import RSSCollector

RSS_XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>GPT-5 Released with Multimodal Capabilities</title>
      <link>https://example.com/gpt5</link>
      <description>OpenAI announces GPT-5 with native multimodal input.</description>
    </item>
    <item>
      <title>LLM Fine-tuning Guide</title>
      <link>https://example.com/finetune</link>
      <description><![CDATA[A comprehensive guide to fine-tuning LLMs.]]></description>
    </item>
    <item>
      <title>No Link Item</title>
      <description>This item has no link.</description>
    </item>
  </channel>
</rss>"""

ATOM_XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>New RAG Framework Released</title>
    <link href="https://example.com/rag-framework"/>
    <summary>A new RAG framework for production use.</summary>
  </entry>
  <entry>
    <title>Agent Toolkit Update</title>
    <link href="https://example.com/agent-toolkit"/>
    <summary>Updated agent toolkit with tool calling support.</summary>
  </entry>
</feed>"""

RSS_CONFIG_SAMPLE = """\
sources:
  - name: Test Feed
    url: https://example.com/feed.xml
    category: ai_research
    enabled: true

  - name: Disabled Feed
    url: https://disabled.com/feed.xml
    category: general_tech
    enabled: false

  - name: Another Feed
    url: https://another.com/rss
    category: company_blog
    enabled: true
"""


class TestRSSXMLParsing:
    """RSS/Atom XML 解析测试。"""

    def test_parse_rss_xml(self) -> None:
        """解析 RSS 2.0 格式 XML。"""
        collector = RSSCollector(limit=10)
        results = collector._parse_xml(RSS_XML_SAMPLE, "Test Feed")

        assert len(results) == 2
        assert results[0]["title"] == "GPT-5 Released with Multimodal Capabilities"
        assert results[0]["url"] == "https://example.com/gpt5"
        assert results[0]["source"] == "hackernews"
        assert results[0]["popularity"] == 0
        assert "collected_at" in results[0]

    def test_parse_atom_xml(self) -> None:
        """解析 Atom 格式 XML。"""
        collector = RSSCollector(limit=10)
        results = collector._parse_xml(ATOM_XML_SAMPLE, "Atom Feed")

        assert len(results) == 2
        assert results[0]["title"] == "New RAG Framework Released"
        assert results[0]["url"] == "https://example.com/rag-framework"
        assert results[0]["summary"] == "A new RAG framework for production use."

    def test_parse_empty_xml(self) -> None:
        """空 XML 返回空列表。"""
        collector = RSSCollector(limit=10)
        results = collector._parse_xml("<rss></rss>", "Empty")
        assert results == []

    def test_parse_skips_items_without_link(self) -> None:
        """缺少 link 的条目被跳过。"""
        collector = RSSCollector(limit=10)
        results = collector._parse_xml(RSS_XML_SAMPLE, "Test Feed")
        titles = [r["title"] for r in results]
        assert "No Link Item" not in titles

    def test_cdata_cleaning(self) -> None:
        """CDATA 内容被正确清理。"""
        collector = RSSCollector(limit=10)
        results = collector._parse_xml(RSS_XML_SAMPLE, "Test Feed")
        cdata_item = [r for r in results if "finetune" in r["url"]]
        assert len(cdata_item) == 1
        assert "CDATA" not in cdata_item[0]["summary"]
        assert "comprehensive guide" in cdata_item[0]["summary"]


class TestRSSConfigLoading:
    """YAML 配置加载测试。"""

    def test_load_enabled_sources(self, tmp_path: Path) -> None:
        """仅加载 enabled: true 的源。"""
        config = tmp_path / "rss_sources.yaml"
        config.write_text(RSS_CONFIG_SAMPLE, encoding="utf-8")

        collector = RSSCollector(limit=10, config_path=config)
        sources = collector._load_sources()

        assert len(sources) == 2
        names = [s["name"] for s in sources]
        assert "Test Feed" in names
        assert "Another Feed" in names
        assert "Disabled Feed" not in names

    def test_load_config_not_found(self, tmp_path: Path) -> None:
        """配置文件不存在时抛出 RuntimeError。"""
        collector = RSSCollector(limit=10, config_path=tmp_path / "nonexistent.yaml")
        with pytest.raises(RuntimeError, match="不存在"):
            collector._load_sources()


class TestRSSCollect:
    """collect 方法测试。"""

    @patch("src.pipeline.rss_collector.httpx.get")
    def test_collect_success(self, mock_get: MagicMock, tmp_path: Path) -> None:
        """正常采集返回候选列表。"""
        config = tmp_path / "rss_sources.yaml"
        config.write_text(RSS_CONFIG_SAMPLE, encoding="utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = RSS_XML_SAMPLE
        mock_get.return_value = mock_resp

        collector = RSSCollector(limit=10, config_path=config)
        results = collector.collect()

        assert len(results) == 4
        assert all(r["source"] == "hackernews" for r in results)

    @patch("src.pipeline.rss_collector.httpx.get")
    def test_collect_skips_failed_source(
        self, mock_get: MagicMock, tmp_path: Path
    ) -> None:
        """单个源失败不影响其他源。"""
        config = tmp_path / "rss_sources.yaml"
        config.write_text(RSS_CONFIG_SAMPLE, encoding="utf-8")

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.text = RSS_XML_SAMPLE

        mock_get.side_effect = [
            httpx.RequestError("connection failed"),
            success_resp,
        ]

        collector = RSSCollector(limit=10, config_path=config)
        results = collector.collect()

        assert len(results) == 2

    @patch("src.pipeline.rss_collector.httpx.get")
    def test_collect_retries_on_429(
        self, mock_get: MagicMock, tmp_path: Path
    ) -> None:
        """429 状态码触发重试。"""
        config = tmp_path / "rss_sources.yaml"
        config.write_text(RSS_CONFIG_SAMPLE, encoding="utf-8")

        retry_resp = MagicMock()
        retry_resp.status_code = 429
        retry_resp.text = "Rate limited"

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.text = RSS_XML_SAMPLE

        mock_get.side_effect = [retry_resp, success_resp, success_resp]

        collector = RSSCollector(limit=10, config_path=config)
        results = collector.collect()

        assert len(results) > 0

    @patch("src.pipeline.rss_collector.httpx.get")
    def test_collect_retries_on_timeout(
        self, mock_get: MagicMock, tmp_path: Path
    ) -> None:
        """超时触发重试。"""
        config = tmp_path / "rss_sources.yaml"
        config.write_text(RSS_CONFIG_SAMPLE, encoding="utf-8")

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.text = RSS_XML_SAMPLE

        mock_get.side_effect = [
            httpx.TimeoutException("timeout"),
            success_resp,
            success_resp,
        ]

        collector = RSSCollector(limit=10, config_path=config)
        results = collector.collect()

        assert len(results) > 0
