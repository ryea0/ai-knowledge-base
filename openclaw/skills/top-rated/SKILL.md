---
name: top-rated
description: 当用户要"推荐 / 高分 / 最佳 / score 最高"的知识库文章时触发。典型用语:推荐几个 xxx / score 最高的 / 最值得看的。基于本地 kb,不需要联网。
allowed-tools:
  - Read
---

# 高分推荐

## 触发词

- 推荐 / 推荐几个
- 最值得看的 / 最有价值的
- score 最高 / 评分最高
- top N / 前 N

## 做法

1. Read `knowledge/articles/index.json` 拿到所有条目的 `article_id` 列表
2. 逐个 Read `knowledge/articles/{article_id}.json`，取 `score`（1-10 整数，缺失为 0）
3. 按 `score` 降序排序
4. 去重（同一个 title 只保留 score 最高的一条）
5. 过滤掉 score < 7 的（不算高分）
6. 默认取 top 5（用户给数字就用用户的，如"推荐 10 篇"）
7. 回复格式:

   ⭐ 高分推荐 top N:

   1. [title](source_url) · score 9/10 · category
      #tag1 #tag2 #tag3 · 2026-07-30
      摘要: ...

## 禁止

- 别 read 目录（EISDIR）
- 别说"我没有 glob 工具"，你只需要 read index.json + 逐个 read 详情文件
- 别返回低于 score 7 的（不算高分）
- 别编造，所有字段严格来自 JSON 文件

## 字段速查

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `article_id` | index.json | 条目 ID，用于拼详情文件路径 |
| `score` | 详情文件 | 1-10 整数，index.json 里没有 |
| `title` | 两者都有 | 标题 |
| `source_url` | 详情文件 | 原始链接 |
| `summary` | 详情文件 | 中文摘要 |
| `tags` | 详情文件 | 标签数组，展示前 3 个 |
| `collected_at` | 详情文件 | 采集时间，取前 10 位 |
| `category` | 两者都有 | 分类 |
