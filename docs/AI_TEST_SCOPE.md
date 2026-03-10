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
| `ai.model` | 传给代理的模型名（由代理映射到 Cursor 后端） | `cursor-default` |

未填写 `base_url` 或 `model` 时，代码使用上述默认值（见 `ai_client.py` 的 `DEFAULT_CURSOR_BASE`、`DEFAULT_CURSOR_MODEL`）。

---

## 三、实际使用的模型与接口

- **接口形态**：**OpenAI 兼容**的 Chat Completions。
- **请求地址**：`{base_url}/chat/completions`，例如 `http://127.0.0.1:8765/v1/chat/completions`。
- **HTTP 方法**：`POST`。
- **认证**：`Authorization: Bearer {api_key}`。
- **模型**：请求体中的 `model` 字段 = config 的 `ai.model`（如 `cursor-default`）。实际使用的 Cursor 模型由本机 **cursor-api-proxy** 根据该名称映射。
- **说明**：不直连 Cursor 官网，只请求本机 **cursor-api-proxy**（默认 `127.0.0.1:8765`），由代理与 Cursor 通信。

---

## 四、调用流程（数据流）

```
1. 主流程（main.py / bot_server.py）
   - 根据 Jira 单号取 CL → P4 取变更文件与 diff → 拼成 full_text
   - 若有变更路径，可选调用 get_project_context() 得到 project_context（项目结构摘要）

2. 若 (ai.api_key 已配置 且 full_text 非空)：
   - 调用 ai_client.get_test_scope_suggestion(
         change_content=full_text,
         api_key=ai.api_key,
         base_url=ai.base_url,
         model=ai.model,
         project_context=project_context,
     )

3. ai_client 内部
   - 使用 config 的 base_url、model（缺省用 Cursor 默认）
   - 将 change_content 截断到 MAX_CONTEXT_CHARS（30000 字符）
   - 固定 system_prompt：测试分析助手，要求根据变更与项目结构给出测试范围建议（中文、分条/分段）
   - user_prompt：项目结构（若有）+ 本次变更内容 + 「请给出需要测试的范围建议」
   - _call_cursor() → POST {base_url}/chat/completions，max_tokens=1500，temperature=0.3

4. 返回值
   - 成功：模型回复文本（最多取前 8000 字符）
   - 失败或未配置：返回 ""

5. 主流程
   - 将返回的字符串写入飞书多维表格「测试范围」列；若为空则该列不写或为空。
```

---

## 五、请求参数小结

| 项目 | 值 |
|------|-----|
| URL | `http://127.0.0.1:8765/v1/chat/completions`（以默认 config 为例） |
| 方法 | POST |
| Headers | `Authorization: Bearer <ai.api_key>`，`Content-Type: application/json` |
| Body | `model`: `ai.model`（如 `cursor-default`）；`messages`: [system, user]；`max_tokens`: 1500；`temperature`: 0.3 |
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

**总结**：测试范围 AI 仅通过 **Cursor 本地代理** 的 **OpenAI 兼容接口** `{base_url}/chat/completions` 调用，模型名为 config 中的 `ai.model`（默认 `cursor-default`），由 cursor-api-proxy 映射到 Cursor 后端。
