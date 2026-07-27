---
name: distribute-message
description: Use when the curator agent needs to publish a reviewed knowledge entry to Telegram or Feishu (Lark). Covers formatting the structured message, calling channel APIs, and updating entry status to published.
---

# Distribute Message

本技能负责将审核完成（`status: reviewed`）的知识条目推送到 Telegram Bot 和飞书 Webhook，并在推送成功后更新条目状态。

## 触发场景

- 整理 Agent 需要将条目分发到 Telegram 时。
- 整理 Agent 需要将条目分发到飞书时。

## 前置条件

- 目标条目 `status` 必须为 `reviewed`，禁止推送 `pending` 条目。
- 以下凭证须从环境变量或 `.env` 读取，严禁硬编码：
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `FEISHU_WEBHOOK_URL`

## 消息格式

推送消息须包含条目的结构化字段，建议格式：

```
<b>{title}</b>

{summary}

🏷 标签：{tags}
🔗 来源：{source_url}
📂 分类：{category}
```

Telegram 使用 HTML 或 Markdown 解析模式；飞书使用交互卡片消息体。

## 工作流程

1. 读取 `knowledge/articles/<id>.json`，确认 `status == "reviewed"`。
2. 按目标渠道格式化消息。
3. 调用对应 API 推送：
   - Telegram：`https://api.telegram.org/bot<token>/sendMessage`
   - 飞书：POST `<FEISHU_WEBHOOK_URL>`
4. 推送成功后更新条目：
   - `status` 置为 `published`
   - `published_at` 填入当前 ISO 8601 UTC 时间
   - `published_channels` 追加已推送的渠道名
5. 推送失败时保留 `reviewed` 状态并记录错误日志，不得标记为 `published`。
6. **写前校验（闸门）**：每次推送须生成分发结果 JSON（结构以本目录 `schema.json` 为唯一真相源），含 `article_id`/`channel`/`status`/`attempted_at`/`published_at`/`error` 字段。**字段不全或类型不合法则禁止写入条目状态**，须修正后重试。
7. **格式冲突仲裁**：若条目 JSON 已存在但字段缺失（如旧版无 `published_channels`），**禁止**降级省略字段；须补全字段后再更新，或记 `WARNING` 跳过并由人工介入。

## 约束

- 禁止在 `published` 后修改条目内容（只能改为 `archived`）。
- 禁止跳过审核直接推送 `pending` 条目。
- **格式不可降级**：分发结果须严格符合本目录 `schema.json`；不得省略字段。
- 禁止裸 `print()`，一律用 `logging`；日志不得输出 Token/Webhook URL 等敏感信息。
- 禁止硬编码 API Key / Token。
- 所有函数须有完整类型注解。

完整规范见项目根目录 `AGENTS.md`。

## 输出格式

每次推送生成分发结果 JSON，结构以本目录 `schema.json` 为唯一真相源，以下示例仅供示意：

```json
{
  "article_id": "kb-20260727-0001",
  "channel": "telegram",
  "status": "success",
  "attempted_at": "2026-07-27T08:10:00Z",
  "published_at": "2026-07-27T08:10:00Z",
  "error": null
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `article_id` | string | 被推送的知识条目业务ID |
| `channel` | string | 推送渠道 `telegram` / `feishu` |
| `status` | string | `success` / `skipped`(已含该渠道) / `failed` |
| `attempted_at` | string | 推送尝试时间，ISO 8601 UTC |
| `published_at` | string\|null | 成功时填条目发布时间；失败/跳过为 null |
| `error` | string\|null | 失败原因；成功/跳过为 null |

> 字段表与 `schema.json` 须始终一致；如有变更，**先改 `schema.json`** 再同步本表与示例。
