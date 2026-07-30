"""AI 知识库评估测试。

评估分析流水线对不同输入的鲁棒性：
    - 正面案例：技术文章输入，预期有摘要、有关键词
    - 负面案例：无关内容输入，预期被过滤或标记为低相关
    - 边界案例：极短输入（如 "AI"），预期不崩溃

LLM 调用通过 litellm 直接请求，不依赖 DB session，适合 CI 中
``pytest -m "not slow"`` 跳过 LLM 测试、``pytest -m slow`` 单独运行。

环境变量：
    从项目根目录 ``.env`` 加载，需配置 ``LLM_API_KEY`` 和 ``LLM_API_BASE``
    （与 ``.env.example`` 中一致）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 环境初始化
# ---------------------------------------------------------------------------

# 加载 .env 到 os.environ，让 litellm 能读到 LLM_API_KEY 等
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ---------------------------------------------------------------------------
# 评估用例定义
# ---------------------------------------------------------------------------

# 分析系统 prompt（复用 nodes.py 中的 _ANALYZE_SYSTEM_PROMPT 结构）
_ANALYZE_PROMPT = (
    "你是一个专业的 AI 技术分析师。请对给定的内容进行分析，"
    "输出严格的 JSON 格式，不要输出任何其他内容。\n"
    "JSON 结构：\n"
    "{\n"
    '  "title": "中文标题（保留专有名词英文）",\n'
    '  "summary": "2-4 句话中文摘要（150 字以内）",\n'
    '  "tags": ["小写英文标签", "3-8 个"],\n'
    '  "score": 1-10 的整数（质量评分）,\n'
    '  "category": "model_release|paper|tool|tutorial|news",\n'
    '  "language": "zh|en"\n'
    "}"
)

# LLM-as-Judge 系统 prompt
_JUDGE_PROMPT = (
    "你是一个严格的技术内容质量评审员。请对以下分析结果打分（1-10 分）。\n"
    "评分维度：摘要准确性、关键词覆盖、分类合理性、信息完整性。\n"
    "只输出一个整数分数，不要输出其他内容。"
)


def _check_positive(result: dict[str, Any]) -> None:
    """正面案例断言：有摘要、有关键词。"""
    assert "summary" in result, "结果缺少 summary 字段"
    assert len(str(result["summary"])) >= 10, "摘要过短"
    assert "tags" in result, "结果缺少 tags 字段"
    assert isinstance(result["tags"], list), "tags 应为列表"
    assert len(result["tags"]) >= 1, "至少应有 1 个标签"


def _check_negative(result: dict[str, Any]) -> None:
    """负面案例断言：低分或低相关。"""
    score = result.get("score", 0)
    assert score <= 6, f"无关内容应低分（<=6），实际 {score}"


def _check_boundary(result: dict[str, Any]) -> None:
    """边界案例断言：不崩溃，返回有效结构。"""
    assert "title" in result, "结果缺少 title 字段"
    assert "summary" in result, "结果缺少 summary 字段"
    assert "score" in result, "结果缺少 score 字段"
    score = result.get("score", 0)
    assert isinstance(score, int | float), f"score 应为数字，实际 {type(score)}"


EVAL_CASES: list[dict[str, Any]] = [
    {
        "name": "positive_tech_article",
        "input": (
            "LangChain v0.3 发布：全新 LCEL 语法、改进的 Agent 架构、"
            "原生支持 OpenAI Functions 和 Anthropic Tool Use。"
            "新版本大幅简化了 RAG 管道构建，提供开箱即用的流式输出。"
            "GitHub Star 数突破 10 万，是目前最流行的 LLM 应用框架之一。"
        ),
        "expected": {
            "check": _check_positive,
            "score_range": (5, 10),
            "category_in": ["model_release", "tool", "tutorial", "news"],
        },
    },
    {
        "name": "negative_irrelevant_content",
        "input": (
            "今天天气不错，适合出门散步。路边的樱花开了，"
            "很多游客在拍照。附近新开了一家咖啡店，拿铁只要 15 元。"
        ),
        "expected": {
            "check": _check_negative,
            "score_range": (1, 6),
            "category_in": ["news"],
        },
    },
    {
        "name": "boundary_minimal_input",
        "input": "AI",
        "expected": {
            "check": _check_boundary,
            "score_range": (1, 10),
            "category_in": ["model_release", "paper", "tool", "tutorial", "news"],
        },
    },
    {
        "name": "real_archived_article",
        "input": (
            "Xnhyacinth/Awesome-LLM-Long-Context-Modeling | Star 2148 | "
            "该仓库汇总了大语言模型长上下文建模领域必读的论文与博客。"
            "内容涵盖长文本处理、注意力机制优化及上下文扩展等核心技术。"
        ),
        "expected": {
            "check": _check_positive,
            "score_range": (6, 10),
            "category_in": ["paper", "tutorial", "tool"],
        },
    },
]


# ---------------------------------------------------------------------------
# LLM 调用辅助
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, system_prompt: str = "") -> str:
    """通过 litellm 调用 LLM，返回纯文本。

    使用 ``.env`` 中的 ``LLM_API_KEY`` / ``LLM_API_BASE`` / ``LLM_MODEL``。

    Args:
        prompt: 用户提问文本。
        system_prompt: 可选的 system 消息。

    Returns:
        LLM 回复文本。

    Raises:
        pytest.skip: 未配置任何 LLM API Key 时跳过。
    """
    # 依次尝试 LLM_API_KEY、CODING_PLAN_API_KEY、AGENT_PLAN_API_KEY
    api_key = (
        os.environ.get("LLM_API_KEY", "")
        or os.environ.get("CODING_PLAN_API_KEY", "")
        or os.environ.get("AGENT_PLAN_API_KEY", "")
    )
    if not api_key:
        pytest.skip(
            "未配置 LLM_API_KEY / CODING_PLAN_API_KEY / "
            "AGENT_PLAN_API_KEY，跳过 LLM 评估测试"
        )

    api_base = os.environ.get(
        "LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3"
    )
    model = os.environ.get("LLM_MODEL", "ark-code-latest")

    import litellm

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = litellm.completion(
        model=f"openai/{model}",
        messages=messages,
        api_key=api_key,
        api_base=api_base,
        temperature=0.3,
        max_tokens=1000,
    )
    return str(response.choices[0]["message"]["content"])


def _parse_analysis(raw: str) -> dict[str, Any]:
    """解析 LLM 分析输出为 JSON dict。

    容忍前后多余文本和 markdown code fence。

    Args:
        raw: LLM 原始输出。

    Returns:
        解析后的 dict。

    Raises:
        ValueError: 无法解析为 JSON dict。
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError(f"JSON 顶层不是 dict: {type(result).__name__}")
    return result


# ---------------------------------------------------------------------------
# 测试：本地验证（不调用 LLM）
# ---------------------------------------------------------------------------


class TestEvalCasesStructure:
    """验证 EVAL_CASES 结构完整性（不调用 LLM）。"""

    def test_cases_count(self) -> None:
        """至少 3 种场景。"""
        assert len(EVAL_CASES) >= 3

    def test_each_case_has_required_fields(self) -> None:
        """每个用例包含 name / input / expected。"""
        for case in EVAL_CASES:
            assert "name" in case, f"用例缺少 name: {case}"
            assert "input" in case, f"用例 {case['name']} 缺少 input"
            assert "expected" in case, f"用例 {case['name']} 缺少 expected"
            assert isinstance(case["input"], str), f"用例 {case['name']} input 非 str"
            assert len(case["input"]) > 0, f"用例 {case['name']} input 为空"

    def test_each_expected_has_check_and_ranges(self) -> None:
        """每个 expected 包含 check 函数、score_range、category_in。"""
        for case in EVAL_CASES:
            exp = case["expected"]
            assert "check" in exp, f"用例 {case['name']} 缺少 check"
            assert callable(exp["check"]), f"用例 {case['name']} check 不可调用"
            assert "score_range" in exp, f"用例 {case['name']} 缺少 score_range"
            sr = exp["score_range"]
            assert isinstance(sr, tuple) and len(sr) == 2
            assert sr[0] <= sr[1], f"用例 {case['name']} score_range 下限 > 上限"
            assert "category_in" in exp, f"用例 {case['name']} 缺少 category_in"
            assert isinstance(exp["category_in"], list)
            assert len(exp["category_in"]) >= 1

    def test_case_names_unique(self) -> None:
        """用例 name 唯一。"""
        names = [c["name"] for c in EVAL_CASES]
        assert len(names) == len(set(names)), "存在重复的用例名"

    def test_positive_case_exists(self) -> None:
        """存在正面案例。"""
        names = [c["name"] for c in EVAL_CASES]
        assert any("positive" in n for n in names), "缺少正面案例"

    def test_negative_case_exists(self) -> None:
        """存在负面案例。"""
        names = [c["name"] for c in EVAL_CASES]
        assert any("negative" in n for n in names), "缺少负面案例"

    def test_boundary_case_exists(self) -> None:
        """存在边界案例。"""
        names = [c["name"] for c in EVAL_CASES]
        assert any("boundary" in n for n in names), "缺少边界案例"


# ---------------------------------------------------------------------------
# 测试：LLM 分析评估（标记 slow）
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestLLMAnalysis:
    """调用真实 LLM 对 EVAL_CASES 做分析评估。"""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=[c["name"] for c in EVAL_CASES])
    def test_analysis_output_valid(self, case: dict[str, Any]) -> None:
        """LLM 分析输出结构有效：可解析 JSON、含必需字段、score 在预期范围。"""
        raw = _call_llm(
            f"请分析以下内容：\n{case['input']}",
            system_prompt=_ANALYZE_PROMPT,
        )
        result = _parse_analysis(raw)

        # 必需字段存在
        assert "title" in result, f"[{case['name']}] 缺少 title"
        assert "summary" in result, f"[{case['name']}] 缺少 summary"
        assert "score" in result, f"[{case['name']}] 缺少 score"
        assert "tags" in result, f"[{case['name']}] 缺少 tags"
        assert "category" in result, f"[{case['name']}] 缺少 category"

        # score 在预期范围内
        score = float(result["score"])
        lo, hi = case["expected"]["score_range"]
        assert lo <= score <= hi, (
            f"[{case['name']}] score={score} 不在范围 [{lo}, {hi}]"
        )

        # category 在预期集合内
        assert result["category"] in case["expected"]["category_in"], (
            f"[{case['name']}] category={result['category']} "
            f"不在 {case['expected']['category_in']}"
        )

        # 运行用例自定义检查函数
        case["expected"]["check"](result)

    @pytest.mark.slow
    def test_llm_as_judge_score(self) -> None:
        """LLM-as-Judge：让 LLM 对正面案例的分析结果打分，断言 >= 5。"""
        positive_case = next(c for c in EVAL_CASES if "positive" in c["name"])

        # 先获取分析结果
        raw_analysis = _call_llm(
            f"请分析以下内容：\n{positive_case['input']}",
            system_prompt=_ANALYZE_PROMPT,
        )
        analysis = _parse_analysis(raw_analysis)

        # 让另一个 LLM 调用做 judge 打分
        judge_raw = _call_llm(
            f"分析结果：\n{json.dumps(analysis, ensure_ascii=False)}\n\n"
            "请对上述分析结果打分（1-10）。",
            system_prompt=_JUDGE_PROMPT,
        )

        # 提取整数分数
        match = re.search(r"\d+", judge_raw.strip())
        assert match is not None, f"Judge 输出无法解析为分数: {judge_raw}"
        score = int(match.group())
        assert score >= 5, f"Judge 打分 {score} < 5，分析质量不达标"


# ---------------------------------------------------------------------------
# 测试：真实归档文章评估（标记 slow）
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRealArchivedArticle:
    """读取工作流真实归档的文章，用 LLM 评估分析质量。

    依赖 ``knowledge/articles/`` 目录下有至少 1 篇已归档文章
    （由 ``run_workflow()`` 产生）。
    """

    def test_eval_archived_article(self) -> None:
        """读取真实归档文章，用 LLM 重新分析并评估。"""
        articles_dir = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
        article_files = sorted(articles_dir.glob("kb-*.json"))
        if not article_files:
            pytest.skip("knowledge/articles/ 无已归档文章，跳过真实文章评估")

        # 取最新的一篇
        article_path = article_files[-1]
        article = json.loads(article_path.read_text(encoding="utf-8"))

        # 构造输入：标题 + 摘要 + 标签
        article_input = (
            f"{article.get('title', '')} | "
            f"source: {article.get('source_url', '')} | "
            f"summary: {article.get('summary', '')}"
        )

        # 用 LLM 重新分析
        raw = _call_llm(
            f"请分析以下内容：\n{article_input}",
            system_prompt=_ANALYZE_PROMPT,
        )
        result = _parse_analysis(raw)

        # 断言结构完整
        assert "title" in result
        assert "summary" in result
        assert "tags" in result
        assert isinstance(result["tags"], list)
        assert len(result["tags"]) >= 1
        assert "category" in result
        assert "score" in result

        # 真实文章 score 应较高
        score = float(result["score"])
        assert score >= 5, f"真实技术文章 score={score} 过低"

        # LLM-as-Judge 打分
        judge_raw = _call_llm(
            f"分析结果：\n{json.dumps(result, ensure_ascii=False)}\n\n"
            "请对上述分析结果打分（1-10）。",
            system_prompt=_JUDGE_PROMPT,
        )
        match = re.search(r"\d+", judge_raw.strip())
        assert match is not None, f"Judge 输出无法解析: {judge_raw}"
        judge_score = int(match.group())
        assert judge_score >= 5, f"Judge 打分 {judge_score} < 5"
