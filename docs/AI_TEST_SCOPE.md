# AI 生成测试范围 — 完整逻辑说明

本文档说明项目中「根据变更内容由 AI 生成测试范围建议」的完整流程。**当前仅支持通过 Cursor 本地代理（cursor-api-proxy）调用**，使用 OpenAI 兼容的 Chat Completions 接口。

---

## 一、何时会调用 AI

在以下三种场景下，**仅当该 Jira 单有关联的 P4 变更列表（CL）且已拿到变更内容**时，才会调用 AI 生成测试范围：

| 场景 | 入口 | 说明 |
|------|------|------|
| 命令行处理单条单子 | `main.py` → `run_single_issue_flow()` | 执行 `python main.py <JIRA_KEY>` 时 |
| 飞书机器人 @ 单号 | `bot_server.py` → `handle_message_event()` | 用户在群内 @ 机器人并发送 Jira 单号 |
| Watcher 定时检测 | `jira_watcher.py` → `main.run_single_issue_flow()` | 每分钟轮询到「分配给我」且需处理的单子时 |

**不调用 AI 的情况：**

- 该单**没有关联 CL**：只写多维表格（经办人、状态等），不请求 AI。
- 配置中 **未配置 `ai.api_key`**：跳过 AI，测试范围为空。
- 变更内容 `full_text` 为空：不调用 AI。

---

## 二、配置（模型与接口）

模型和接口由 **`config.json` 的 `ai` 段** 决定：

| 配置项 | 含义 | 默认值 |
|--------|------|--------|
| `ai.api_key` | 调用代理的密钥（代理不校验时可填任意非空字符串） | — |
| `ai.base_url` | Cursor 代理根地址（不含路径） | `http://127.0.0.1:8765/v1` |
| `ai.model` | 传给代理的模型名（由代理映射到 Cursor 后端） | `auto`（或 composer-1.5、gpt-5.2 等） |

未填写 `base_url` 或 `model` 时，代码使用上述默认值（见 `ai_client.py` 的 `DEFAULT_CURSOR_BASE`、`DEFAULT_CURSOR_MODEL`）。

---

## 三、实际使用的模型与接口

- **接口形态**：**OpenAI 兼容**的 Chat Completions。
- **请求地址**：`{base_url}/chat/completions`，例如 `http://127.0.0.1:8765/v1/chat/completions`。
- **HTTP 方法**：`POST`。
- **认证**：`Authorization: Bearer {api_key}`。
- **模型**：请求体中的 `model` 字段 = config 的 `ai.model`（如 `auto`）。实际使用的 Cursor 模型由本机 **cursor-api-proxy** / agent 根据该名称映射（`auto` 表示自动选择）。
- **说明**：不直连 Cursor 官网，只请求本机 **cursor-api-proxy**（默认 `127.0.0.1:8765`），由代理与 Cursor 通信。

---

## 四、调用流程（数据流）

```
1. 主流程（main.py / bot_server.py）
   - 根据 Jira 单号取 CL → P4 取变更文件与 diff → 拼成 full_text
   - 从 files_by_cl 抽成变更路径列表 change_paths（去重），作为「本次变更清单」
   - 若有变更路径，可选调用 get_project_context()、get_game_project_structure() 得到 project_context、game_project_context

2. 若 (ai.api_key 已配置 且 full_text 非空)：
   - 调用 ai_client.get_test_scope_suggestion(
         change_content=full_text,
         ...,
         change_list=change_paths,  # 本次变更清单（改动路径，每行一条）
     )

3. ai_client 内部
   - 使用 config 的 base_url、model（缺省用 Cursor 默认）
   - 将 change_content 截断到 MAX_CONTEXT_CHARS（6000 字符）
   - 组装 user_prompt，**明确提供两类信息**，避免 AI 称「工作区为空、看不到改动」：
     - 【本次变更清单】：change_list 中的路径，每行一条（如 entity/theme/crop.xlsx、logic/cookingRecipe.xlsx）
     - 【变更内容摘要】：full_text（每个文件改了什么：新增字段/改公式/改触发条件/改数值区间等）
     - 【变更文件内容预览】（方法2）：对变更路径用 `p4 print` 拉取文件内容（跳过二进制/Office），拼成一段文字并入第一类信息，供 AI 结合路径与摘要分析，不依赖 agent 工作区
   - 要求 AI **严格按三步结构**输出：
     1. 变更面识别（配置/逻辑）
     2. 影响链路展开（上下游）
     3. 测试范围输出（可执行：配置联动校验、功能回归、风险专项）
   - _call_cursor() → POST {base_url}/chat/completions，max_tokens=1500，temperature=0.3

4. 返回值
   - 成功：(value_for_bitable, raw_response)，前者经规则过滤后写入表格，后者原样打日志
   - 失败或未配置：("", "")

5. 主流程
   - 将 value_for_bitable 写入飞书多维表格「测试范围」列；若为空则该列不写或为空。
```

---

## 五、请求参数小结

| 项目 | 值 |
|------|-----|
| URL | `http://127.0.0.1:8765/v1/chat/completions`（以默认 config 为例） |
| 方法 | POST |
| Headers | `Authorization: Bearer <ai.api_key>`，`Content-Type: application/json` |
| Body | `model`: `ai.model`（如 `auto`）；`messages`: [system, user]；`max_tokens`: 1500；`temperature`: 0.3 |
| 超时 | 60 秒 |

---

## 六、相关代码位置

| 文件 | 作用 |
|------|------|
| `ai_client.py` | 唯一调用 AI 的模块：`get_test_scope_suggestion()`、`_call_cursor()`，以及 Cursor 默认 base_url / model |
| `main.py` | 组装 full_text、project_context，读取 config 的 `ai`，调用 `get_test_scope_suggestion`，结果写入 Bitable |
| `bot_server.py` | 同上，在 @ 单号处理分支中调用 |
| `jira_watcher.py` | 通过 `main.run_single_issue_flow()` 间接使用同一套 AI 逻辑 |
| `feishu_client.py` | `add_report_to_bitable()` 将 `test_scope` 写入多维表格「测试范围」列 |

---

**总结**：测试范围 AI 仅通过 **Cursor 本地代理** 的 **OpenAI 兼容接口** `{base_url}/chat/completions` 调用，模型名为 config 中的 `ai.model`（默认 `auto`），由 cursor-api-proxy 映射到 Cursor 后端。

---

## 调试：确认 P4 内容是否随请求发出

若 AI 返回泛化内容（如 P0/P1、接口契约、权限隔离等）而无游戏向、具体 ID/表名，可先确认「第一类信息」「第二类信息」是否真的随请求发出：

1. **完整 prompt 每次都会写入文件**：每次调用 AI 时，脚本都会把本次发给 AI 的完整 prompt 写入项目目录下的 `last_ai_prompt.txt`（与是否设置 debug 无关）。打开该文件检查是否包含：
   - 【变更路径清单】及具体 depot 路径
   - 【变更内容摘要】及 P4 describe / xlsx 单元格变更摘要
   - 【变更文件内容预览】（若变更为 .cs/.lua/.json 等会拉取 p4 print 内容；若全为 .xlsx/.dll 等则为空）
   - 【项目背景】/【P4 depot 项目结构】/【游戏工程目录结构】
2. **P4 print 是否拉取到内容**：在 `FEISHU_REPORT_DOC_DEBUG=1` 时，控制台会打印「P4 print 拉取内容长度: N 字」。若为 0 且变更多为 xlsx/二进制，则「变更文件内容预览」为空，但「变更内容摘要」中仍应有 p4 describe 及（对 xlsx）openpyxl 的单元格级摘要。
3. 若 `last_ai_prompt.txt` 中已有完整变更路径与摘要，而 AI 仍只返回泛化条目，多为模型未按指令使用上下文或代理对请求体做了截断，可尝试缩短 prompt 或更换模型。

---

## 为何开/关 AI_PROMPT_DEBUG 会得到不同回复？

脚本**每次**都会把 prompt 写入 `last_ai_prompt.txt`；**AI_PROMPT_DEBUG** 只控制是否在控制台打印该文件路径与「本次发送 prompt 长度」。发给代理的请求内容与 debug 开关无关。

若出现「同单号、同模型，有时输出正常有时回复请提供第一类/第二类信息」：

- **原因**：代理或 Cursor 对请求体有**截断或限长**，且不稳定，导致有时模型收到完整 prompt、有时只收到后半段（缺数据）。
- **已做**：已收紧各块上限（变更摘要 4000、P4 文件内容 3000、项目/游戏结构各 500、变更路径 1500），并缩短指令，使总 prompt 更短、更易完整通过代理。
- **排查**：设 `FEISHU_REPORT_DOC_DEBUG=1` 看「本次发送 prompt 长度: N 字」。若仍不稳定，可在 cursor-api-proxy 侧检查请求体大小限制或进一步缩短 prompt。
