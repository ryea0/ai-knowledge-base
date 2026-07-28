"""多渠道分发模块。

将已审核（``status: reviewed``）的知识条目推送至 Telegram / 飞书等渠道。
推送成功后在同一事务内更新 ``published_channels`` 和 ``status``/``published_at``。

子模块：
    - ``base``: 分发器抽象基类
    - ``telegram``: Telegram Bot 推送
    - ``feishu``: 飞书 Webhook 推送
"""

from src.distributors.base import BaseDistributor

__all__ = ["BaseDistributor"]
