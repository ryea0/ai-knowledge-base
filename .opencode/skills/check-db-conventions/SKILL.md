---
name: check-db-conventions
description: 检查 DDL / ORM / 查询代码是否符合 docs/specs/db-conventions.md §7 数据库设计规范（必选字段、软删除、唯一约束 guard 列、查询过滤 is_deleted）。在新建表、修改表结构或编写 ORM 查询后使用。
allowed-tools:
  - Read
  - Grep
  - Glob
---

# 检查数据库设计规范合规性

## 使用场景

- 新建 DB 表（DDL 文件）后检查必选字段是否齐全。
- 修改 ORM 模型后检查与 DDL 是否一致。
- 编写查询代码后检查是否过滤 `is_deleted = 0`。
- Code review 时作为自动化检查清单。

## 检查清单

### 1. 必选字段（docs/specs/db-conventions.md §7.1）

每张**业务表**（非纯追加日志表）必须包含以下字段，检查 DDL 和 ORM 是否齐全：

| 字段 | DDL 定义 | ORM 类型 | 约束 |
|------|---------|---------|------|
| `id` | `BIGINT UNSIGNED NOT NULL AUTO_INCREMENT` | `Integer, primary_key=True` | 主键 |
| `created_at` | `DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP` | `DateTime, nullable=False` | — |
| `updated_at` | `DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | `DateTime, nullable=False, onupdate=...` | 须有 `ON UPDATE` |
| `is_deleted` | `TINYINT(1) UNSIGNED NOT NULL DEFAULT 0` | `Integer, nullable=False, default=False` | 默认 0 |
| `deleted_at` | `DATETIME(3) NULL` | `DateTime, nullable=True` | — |

**纯追加日志表**（如 `kb_llm_call_log`）例外：仅需 `id` + `created_at`，不需要 `updated_at` / `is_deleted` / `deleted_at`。日志表须在注释中标注 "append-only"。

### 2. 软删除（docs/specs/db-conventions.md §7.1）

- **禁止物理删除**：代码中禁止 `session.delete(obj)` 或 `DELETE FROM` 语句（清理过期日志的运维脚本除外，须在 `scripts/` 下）。
- **删除操作**：须 `UPDATE SET is_deleted=1, deleted_at=NOW(3)`，ORM 层设 `obj.is_deleted = True; obj.deleted_at = datetime.now(UTC)`。
- **所有查询过滤**：业务查询须加 `WHERE is_deleted = 0`（ORM: `.where(Model.is_deleted == False)`）。
  - **例外**：管理后台查看回收站时可不过滤，但须在代码注释中说明。

### 3. 唯一约束与 guard 列（docs/specs/db-conventions.md §7.1）

- 业务表的唯一约束须使用 **guard 生成列**排除软删除行。
- guard 列定义模式：`CASE WHEN is_deleted=0 THEN CONCAT('prefix:', value) ELSE NULL END STORED`。
- 唯一索引建在 guard 列上（`UNIQUE KEY uk_xxx_guard (xxx_guard)`），而非原始列。
- MySQL 唯一索引允许多个 NULL，因此软删除行（guard=NULL）不占用唯一约束。

检查方法：Grep 搜索 DDL 中的 `UNIQUE KEY`，确认是否带 `_guard` 后缀；若直接对业务列建唯一索引，须改为 guard 列。

### 4. 索引规范（docs/specs/db-conventions.md §7.3）

- 每张表须有 `KEY idx_is_deleted (is_deleted)`。
- 索引命名：普通 `idx_`、唯一 `uk_`、全文 `ft_`。
- 单表索引 ≤ 5 个，单索引 ≤ 5 列。
- 禁止 `SELECT *`。

### 5. ORM 与 DDL 一致性

- ORM 模型的字段数、类型、nullable 须与 DDL 一致。
- ORM 模型须包含 `is_deleted` 和 `deleted_at` 字段（日志表除外）。

## 执行步骤

1. **扫描 DDL 文件**：Glob `deploy/sql/*.sql` 和 `deploy/docker/init.sql`，逐文件检查必选字段。
2. **扫描 ORM 文件**：Glob `src/**/orm.py`，逐类检查字段与 DDL 对齐。
3. **扫描查询代码**：Grep `session.execute(select(` 或 `.where(`，检查是否过滤 `is_deleted`。
4. **扫描物理删除**：Grep `session.delete(` 和 `DELETE FROM`，确认无业务代码使用（`scripts/` 下除外）。
5. **输出报告**：列出所有不合规项，按严重程度排序（ERROR / WARNING）。

## 输出格式

```
## DB 规范检查报告

### ERROR（必须修复）

- [deploy/sql/01_kb_llm_provider.sql] 缺少 `is_deleted` 字段
- [src/llm/service.py:152] delete_provider 使用物理删除，须改为软删除
- [src/llm/router.py:44] 查询未过滤 `is_deleted = 0`

### WARNING（建议修复）

- [deploy/sql/02_kb_llm_model.sql] uk_provider_model 直接对业务列建唯一索引，建议改用 guard 列

### PASS

- [deploy/sql/08_kb_llm_call_log.sql] 纯追加日志表，仅需 id + created_at ✓
- [src/llm/orm.py] 所有 ORM 模型字段与 DDL 一致 ✓
```
