"""知识条目相关枚举定义。

本模块是 status / category / source_platform 等枚举的**唯一定义点**。
DB 存整数值，JSON 写字符串名；docs/specs/content-spec.md §6.6 的映射表须与本文件保持一致。
新增/变更状态须先改本文件，再同步文档。
LLM 供应商相关枚举见本文件末尾，映射见 docs/specs/llm-provider.md §9。
"""

from enum import IntEnum


class ArticleStatus(IntEnum):
    """知识条目生命周期状态。

    DB 存 TINYINT（本枚举的整数值），JSON 写 ``.name`` 小写形式。
    转换矩阵见 docs/specs/content-spec.md §6.6。
    """

    PENDING = 0
    REVIEWED = 1
    PUBLISHED = 2
    ARCHIVED = 3

    def to_json_str(self) -> str:
        """转为 JSON 文件中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "ArticleStatus":
        """从 JSON 字符串名解析。

        Args:
            value: JSON 中存储的状态字符串，如 "pending"。

        Returns:
            对应的 ArticleStatus 枚举成员。

        Raises:
            ValueError: value 不是合法的状态字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的状态字符串: {value}，合法值: {valid}") from exc


class Category(IntEnum):
    """知识条目内容分类。

    判定标准见 docs/specs/content-spec.md §6.5。DB 存 VARCHAR 字符串名（非 TINYINT），
    因分类值可能扩展且无排序需求，直接存字符串更易读。
    """

    MODEL_RELEASE = 0
    PAPER = 1
    TOOL = 2
    TUTORIAL = 3
    NEWS = 4

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "Category":
        """从字符串名解析。

        Args:
            value: 分类字符串，如 "model_release"。

        Returns:
            对应的 Category 枚举成员。

        Raises:
            ValueError: value 不是合法的分类字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的分类字符串: {value}，合法值: {valid}") from exc


class SourcePlatform(IntEnum):
    """知识条目来源平台。

    新增来源须同步更新 docs/specs/article-format.md §4、docs/specs/db-conventions.md §7.5 注释。
    """

    GITHUB_TRENDING = 0
    HACKERNEWS = 1

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "SourcePlatform":
        """从字符串名解析。

        Args:
            value: 平台字符串，如 "github_trending"。

        Returns:
            对应的 SourcePlatform 枚举成员。

        Raises:
            ValueError: value 不是合法的平台字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的平台字符串: {value}，合法值: {valid}") from exc


class LlmProviderType(IntEnum):
    """LLM 供应商类型。

    DB 存 TINYINT（本枚举的整数值），JSON 写 ``.name`` 小写形式。
    映射见 docs/specs/llm-provider.md §9.1。
    """

    CLOUD = 0
    LOCAL = 1

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "LlmProviderType":
        """从字符串名解析。

        Args:
            value: 类型字符串，如 "cloud"。

        Returns:
            对应的 LlmProviderType 枚举成员。

        Raises:
            ValueError: value 不是合法的类型字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的供应商类型字符串: {value}，合法值: {valid}") from exc


class LlmAuthType(IntEnum):
    """LLM 供应商鉴权方式。

    DB 存 TINYINT，JSON 写 ``.name`` 小写形式。
    主凭证统一存 ``api_key_encrypted``，附加凭证存 ``auth_config`` JSON。
    映射见 docs/specs/llm-provider.md §9.1。
    """

    BEARER = 0   # Authorization: Bearer <key>，仅需 api_key
    OAUTH = 1    # OAuth 换 access_token（如百度），需 api_key + secret_key
    HEADER = 2   # 自定义 header（如 Google: x-goog-api-key），需 api_key + header_name
    NONE = 3     # 无鉴权（Ollama / llama.cpp）

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "LlmAuthType":
        """从字符串名解析。

        Args:
            value: 鉴权类型字符串，如 "bearer"。

        Returns:
            对应的 LlmAuthType 枚举成员。

        Raises:
            ValueError: value 不是合法的鉴权类型字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的鉴权类型字符串: {value}，合法值: {valid}") from exc


class LlmHealthStatus(IntEnum):
    """LLM 供应商健康状态（类熔断器模式）。

    DB 存 TINYINT，JSON 写 ``.name`` 小写形式。
    状态机转换规则见 docs/specs/llm-provider.md §9.2。
    """

    HEALTHY = 0    # 正常可用
    DEGRADED = 1   # 降级（连续失败 < 阈值，仍可尝试）
    UNHEALTHY = 2  # 不可用（连续失败 >= 阈值，路由跳过）
    UNKNOWN = 3    # 未检测（新供应商 / 重置后）

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "LlmHealthStatus":
        """从字符串名解析。

        Args:
            value: 健康状态字符串，如 "healthy"。

        Returns:
            对应的 LlmHealthStatus 枚举成员。

        Raises:
            ValueError: value 不是合法的健康状态字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的健康状态字符串: {value}，合法值: {valid}") from exc


class LlmModelSource(IntEnum):
    """LLM 模型记录来源。

    DB 存 TINYINT，JSON 写 ``.name`` 小写形式。
    映射见 docs/specs/llm-provider.md §9.1。
    """

    PRESET = 0     # 系统预置种子数据
    DISCOVERED = 1 # 通过 /v1/models 自动发现
    MANUAL = 2     # 前端手动添加

    def to_json_str(self) -> str:
        """转为 JSON / DB 中存储的字符串名。"""
        return self.name.lower()

    @classmethod
    def from_json_str(cls, value: str) -> "LlmModelSource":
        """从字符串名解析。

        Args:
            value: 来源字符串，如 "preset"。

        Returns:
            对应的 LlmModelSource 枚举成员。

        Raises:
            ValueError: value 不是合法的来源字符串。
        """
        try:
            return cls[value.upper()]
        except KeyError as exc:
            valid = [m.to_json_str() for m in cls]
            raise ValueError(f"无效的模型来源字符串: {value}，合法值: {valid}") from exc
