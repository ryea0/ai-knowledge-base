import type { Plugin } from "@opencode-ai/plugin"

/**
 * 知识条目 JSON 写入后自动校验插件。
 *
 * 监听 tool.execute.after 事件，当 Agent 使用 write/edit 工具写入
 * knowledge/articles/*.json 时，自动调用 hooks/validate_json.py 校验。
 *
 * 关键约束：
 * - 使用 Bun Shell $ 模板字符串执行命令
 * - 必须用 .nothrow() 而非 .quiet()（.quiet() 会导致 OpenCode 卡死）
 * - 所有 shell 调用须 try/catch 包裹（未捕获异常会阻塞 Agent）
 */

const KNOWLEDGE_ARTICLES_PATTERN = "knowledge/articles/"
const VALIDATE_SCRIPT = "hooks/validate_json.py"

/**
 * 从 input.args 中提取文件路径，兼容 file_path / filePath 两种命名。
 */
function getFilePath(args: Record<string, unknown>): string | undefined {
  const raw = (args.file_path ?? args.filePath) as string | undefined
  return typeof raw === "string" ? raw : undefined
}

/**
 * 判断文件路径是否为 knowledge/articles/ 下的 JSON 文件。
 */
function isKnowledgeArticle(filePath: string): boolean {
  return filePath.endsWith(".json") && filePath.includes(KNOWLEDGE_ARTICLES_PATTERN)
}

export const ValidatePlugin: Plugin = async ({ $, directory }) => {
  return {
    "tool.execute.after": async (input, output) => {
      try {
        if (input.tool !== "write" && input.tool !== "edit") {
          return
        }

        const args = (input.args ?? {}) as Record<string, unknown>
        const filePath = getFilePath(args)
        if (!filePath || !isKnowledgeArticle(filePath)) {
          return
        }

        // 使用 Bun Shell 执行校验脚本，.nothrow() 避免非零退出码抛异常导致卡死
        const result = await $`python3 ${VALIDATE_SCRIPT} ${filePath}`
          .cwd(directory)
          .nothrow()

        // 校验失败（exit 1）时将错误信息注入工具输出
        if (result.exitCode !== 0) {
          const detail = result.text() || result.stderr.toString()
          output.output = `⚠ JSON 校验失败 (${filePath}):\n${detail}`
        }
      } catch (err) {
        // 捕获所有异常，防止未处理错误阻塞 Agent 执行
        output.output = `⚠ 校验插件异常: ${err instanceof Error ? err.message : String(err)}`
      }
    },
  }
}

export default ValidatePlugin
