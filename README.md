# Jira + P4 + 飞书提醒工具

根据 Jira 单号读取关联的 P4 CL，查询变更文件，在飞书群发送提醒；支持群内 @ 机器人查单号、Jira 分配监控自动触发。

---

## 功能

- **命令行**：`python main.py PROJ-1234`，向配置的飞书群发送该单号的 P4 变更摘要。
- **群内 @ 机器人**：在飞书群 @ 机器人并发送 Jira 单号，机器人回复该单号的 P4 变更（需单独运行 `bot_server_ws.py` 并配置事件订阅，见下）。
- **Jira 分配监控**：运行 `python jira_watcher.py` 常驻，按间隔轮询「经办人=当前用户或额外名单」且可设状态（如 Testing）的单子，对新分配或已更新的单子自动执行与 main.py 相同的流程（P4 变更、多维表格、AI 测试范围、发飞书）。

## 环境要求

- Python 3.9+
- 已安装 Perforce 命令行 `p4`（且在 PATH 中）
- Jira 账号与 API Token
- 飞书企业自建应用（机器人已开启并加入目标群）

---

## 安装

```bash
cd jira-p4-feishu
pip install -r requirements.txt
```

---

## 配置

在项目目录新建 `config.json`（或使用 `.env` 环境变量），按实际环境填写下列配置项。

### 配置项说明

| 配置项 | 说明 |
|--------|------|
| **Jira** | |
| `base_url` | Jira 站点地址 |
| `email` / `api_token` | 登录 Jira 的邮箱与 [API Token](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `cl_custom_field_id` | 存放 P4 CL 的 Jira 自定义字段 id，如 `customfield_10050` |
| **P4** | `cwd` 可选，不填则用当前环境（P4PORT、P4USER 等） |
| **飞书** | |
| `app_id` / `app_secret` | 飞书应用凭证 |
| `receive_id` | 群聊的 `chat_id`（发到群）或用户的 `open_id` |
| `receive_id_type` | `chat_id` 或 `open_id`，默认 `chat_id` |
| `bitable_app_token` / `bitable_table_id` | 多维表格 app_token 与 table_id；或仅填 `bitable_wiki_node_token` + `bitable_table_id` 由工具解析 app_token |
| `tenant_base_url` | 企业飞书域名，如 `https://xd.feishu.cn`，用于生成消息中的多维表格可打开链接（不填则用 open.feishu.cn 链接，可能提示页面不存在） |
| `bitable_view_id` | 多维表格视图 ID（可选），填后链接会带 `&view=xxx`，直接打开指定视图 |
| `assignee_open_id_map` | 可选。Jira 经办人显示名 → 飞书 open_id，用于消息中 @ 经办人，如 `{"姚博 YaoBo": "ou_xxx"}`。open_id 可在飞书管理后台或通过「获取用户信息」API 获取 |
| **AI** | `ai.api_key`、`ai.provider`（如 `gemini`）、`ai.base_url`、`ai.model` 可选 |`ai.api_key`、`ai.provider`（如 `gemini`）、`ai.base_url`、`ai.model` 可选 |
| **Watcher** | |
| `watcher.poll_interval_seconds` | 轮询间隔（秒），默认 300 |
| `watcher.state_file` | 状态文件路径，不填则用项目目录下 `watcher_state.json` |
| `watcher.jql_extra` | 可选 JQL 条件，如 `AND project = PROJ` |
| `watcher.assignee_extra` | 额外监听的经办人 Jira 用户名列表，如 `["YaoBo"]` 或逗号分隔字符串 `"YaoBo,user2"`，与当前用户一起被监控 |
| `watcher.status_filter` | 只监控该状态的单子，如 `Testing` |
| `watcher.completed_statuses` | 视为「终态」的状态列表，如 `["已完成", "已取消"]`。状态同步时若单号变为其中任一状态，则不再检测该单号（不请求 Jira），直到其再次变为 `status_filter` 的状态后恢复检测。默认 `["已完成", "已取消"]` |
| `watcher.skip_if_in_bitable` | 为 true（默认）时，若该 JIRA 单号已存在于多维表格则跳过 |
| `watcher.no_notify_if_no_cl` | 无 CL 时是否不往飞书发「暂无关联 CL」 |

### 获取 Jira 自定义字段 id

浏览器打开 `https://<你的Jira域名>/rest/api/2/field`，在返回 JSON 中找到存放 P4 CL 的字段的 `id`（形如 `customfield_10050`），填到 `cl_custom_field_id`。

### 飞书应用与机器人配置

1. **创建应用**：打开 [飞书开放平台](https://open.feishu.cn/app) → 创建企业自建应用 → 记下 **App ID**、**App Secret**。
2. **开启机器人**：应用内「功能」→「机器人」→ 启用机器人。
3. **权限**：「权限管理」中申请并让管理员通过：发送消息、获取群信息等；若需群内 @ 回复，还需「获取用户在群组中 @ 机器人的消息」。
4. **发布**：「版本管理与发布」中发布应用，并设置可用范围（全员或指定范围）。
5. **拉群**：在飞书客户端把该应用机器人加入目标群。
6. **获取 chat_id**：通过事件订阅「机器人进群」收到事件中的 `event.chat_id`，或调用「搜索群列表」API 获取目标群的 `chat_id`，填到 `receive_id`。

常见错误：230002（机器人不在群）、230006（未开机器人）、99991401（权限未生效）— 检查机器人已入群、权限已通过、应用已发布且可用。

---

## 使用

### 命令行单次执行

```bash
python main.py PROJ-1234
```

未找到 CL 时默认仍会发飞书「暂无关联 CL」；若不想发：`python main.py PROJ-1234 --no-notify-if-no-cl`。

### Jira 分配监控（常驻）

```bash
python jira_watcher.py
```

- 按 `watcher.poll_interval_seconds` 轮询；状态文件默认 `watcher_state.json`，日志默认控制台 + `jira_watcher.log`。
- 同一单子若在 Jira 再次更新会再执行一次；若单子不再「分配给我」会从状态移除。退出：Ctrl+C。
- **状态同步**：每轮会查询多维表格中已有记录的 JIRA 单号，若 Jira 状态与表中「JIRA单据状态」不一致则仅更新该列；若某条记录的「经办人」或「JIRA单据状态」为空，会从 Jira 拉取并回填（不触发 P4/AI）。当某单号状态变为「已完成/已取消」（可由 `watcher.completed_statuses` 配置）时，该单号会被加入跳过集合，之后轮询不再请求 Jira，直到其状态再次变为 `status_filter`（如 Testing）时自动恢复检测。
- 设置 `JIRA_WATCHER_DEBUG=1` 可开调试日志。

### 群内 @ 机器人查单号

**推荐：长连接（无需公网）**

1. 飞书开放平台 → 你的应用 → 事件订阅 → 选择 **「使用长连接接收事件」**，订阅 **接收消息**（`im.message.receive_v1`）。
2. **先**在本机执行并保持运行：`python bot_server_ws.py`，看到长连接成功后再去飞书后台点击保存（飞书会校验是否已有连接）。
3. 在群里 @ 机器人并发送 Jira 单号即可收到回复。

发消息无反应时：看运行 `bot_server_ws.py` 的终端是否有报错；设置 `FEISHU_BOT_DEBUG=1` 后重启再试，并确认应用已开通「获取用户在群组中 @ 机器人的消息」并发布生效。

**可选：Webhook 方式**（需公网 HTTPS）  
若选用「请求 URL」方式，需提供公网 HTTPS 地址（如 ngrok：`ngrok http 9000`，飞书请求 URL 填 `https://xxx/feishu_event`）；本地运行 `python bot_server.py` 监听 9000。一般推荐长连接省去公网与证书。

---

## 消息与多维表格

- **飞书消息**：仅展示时间、标题、CL 号、文件列表、变更分析及 Jira 链接；行级 diff 等详见多维表格或云文档。
- **多维表格**：配置 `bitable_app_token`+`bitable_table_id`（或 `bitable_wiki_node_token`+`bitable_table_id`）后，每次会写入/更新多维表格，消息中带表格链接。表需包含列：JIRA单号、JIRA单标题、JIRA单修改时间、JIRA单创建人、**经办人**、**JIRA单据状态**、变更CL号、变更文件、变更具体内容；若启用 AI 测试范围，再加一列「测试范围」。同一 JIRA 单号已存在则覆盖该记录。无 CL 的单也会录入（经办人、状态、标题等），变更文件/内容/测试范围为空。
- **云文档**：未配置多维表格时会尝试创建飞书云文档写入完整内容，需应用有创建文档权限。
- **AI 测试范围**：配置 `ai.api_key` 后，会根据变更内容（及变更区域的项目结构）调用大模型生成测试范围建议并写入表格「测试范围」列；`ai.provider": "gemini"` 使用 Google Gemini。

---

## 持续运行与部署

### Docker

```bash
docker build -t jira-p4-feishu .
docker run -d --name jira-watcher --restart unless-stopped \
  -v "$(pwd)/config.json:/app/config.json:ro" \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/watcher_state.json:/app/watcher_state.json" \
  -v "$(pwd)/jira_watcher.log:/app/jira_watcher.log" \
  jira-p4-feishu
```

或使用 `docker-compose up -d watcher`（需先存在 config.json、.env）。容器内无 P4 时 P4 相关步骤会失败，可仅在需 P4 的节点用下面方式跑。

### Jenkins 部署（一步一步）

**前提**：Jenkins 已安装；执行节点已装 Python 3.9+（且 `python` 或 `python3` 在 PATH 中）；若需要 P4 查变更，该节点需能执行 `p4` 并配置好环境。

1. **准备代码与配置**
   - 把本仓库推到 Git（GitLab/GitHub/内网 Git），或把整个项目目录拷贝到 Jenkins 某节点的固定路径（如 `D:\jenkins\jira-p4-feishu`）。
   - 在该目录下放好 **config.json** 和（可选）**.env**，内容按上文「配置」填写，不要提交到 Git。

2. **新建任务**
   - Jenkins 首页 → **新建任务**。
   - 输入任务名称（如 `jira-p4-feishu-watcher`）。
   - 选择 **「构建一个自由风格的软件项目」**（或 **Pipeline**，见第 5 步）。
   - 点击 **确定**。

3. **禁止并发构建**
   - 在任务配置页，**通用** 里勾选 **「禁止并发构建」**，避免同一任务启动多个 watcher。

4. **源码管理（二选一）**
   - **用 Git**：**源码管理** 选 **Git**，填仓库 URL、凭据、分支。构建时工作区会拉取代码，但 config.json、.env 不在仓库里，需在节点上该工作区目录下手动放一份，或在「构建」里用凭据写出（见下）。
   - **不用 Git**：源码管理留空，**构建** 里用 `cd` 进入你拷贝好的项目路径（如 `D:\jenkins\jira-p4-feishu`）。

5. **构建步骤（自由风格）**
   - **构建** → **增加构建步骤** → **Execute Windows batch command**（Windows 节点）或 **Execute shell**（Linux 节点）。
   - 填入下面其中一段（按你实际情况改路径）。

   **Windows 示例（项目在 `D:\jenkins\jira-p4-feishu`）：**
   ```bat
   cd /d D:\jenkins\jira-p4-feishu
   pip install -r requirements.txt -q
   python -u jira_watcher.py
   ```

   **Linux 示例（项目在 `/var/jenkins/jira-p4-feishu`）：**
   ```bash
   cd /var/jenkins/jira-p4-feishu
   pip install -r requirements.txt -q
   python -u jira_watcher.py
   ```

   **若用 Git 拉代码（工作区在 Jenkins 默认 workspace，且仓库根就是 jira-p4-feishu）：**
   ```bash
   cd jira-p4-feishu
   pip install -r requirements.txt -q
   python -u jira_watcher.py
   ```
   此时需保证该目录下已有 config.json（可在首次构建前手动拷进去，或通过 Jenkins 凭据在脚本里写出）。

6. **保存并运行**
   - 点击 **保存**。
   - 点击 **立即构建**。构建会一直处于「执行中」，控制台会持续输出 watcher 的轮询日志。
   - 需要停止时：进入该次构建 → **终止构建**。

7. **（可选）用 Pipeline 代替自由风格**
   - 新建任务时选 **Pipeline**。
   - **Pipeline** → **Definition** 选 **Pipeline script from SCM**，填 Git 仓库与凭据，**Script Path** 填 `Jenkinsfile.watcher`。
   - 若仓库根就是 jira-p4-feishu，把仓库里的 `Jenkinsfile.watcher` 中 `dir('jira-p4-feishu')` 去掉，只保留 `pip install` 和 `python -u jira_watcher.py`。
   - 仓库内 `Jenkinsfile.watcher` 已包含长超时与禁止并发，保存后 **立即构建** 即可长期运行，停止时点「终止构建」。

8. **验证**
   - 打开某次构建的 **控制台输出**，应看到 `[Watcher] ========  Jira 分配监控已启动  ========` 和「开始轮询 Jira」。
   - 在 Jira 里把某单子经办人设为自己、状态设为 Testing，若该单未写入多维表格，下一次轮询后应会发飞书并写表格。

### Windows / Linux 本机常驻

- **Windows**：计划任务或 NSSM 将 `python -u jira_watcher.py` 设为登录/启动时运行，工作目录设为项目目录。
- **Linux**：使用 systemd 服务，`ExecStart=/usr/bin/python3 -u jira_watcher.py`，`WorkingDirectory` 设为项目路径，`Restart=always`。

Watcher 与飞书机器人可同时运行：一个 Job/进程跑 `jira_watcher.py`，另一个跑 `bot_server_ws.py`，共用同一 config。

---

## 错误处理

- Jira 单号不存在或无权：提示并退出，不发飞书。
- 自定义字段为空：视为未找到 CL，按配置决定是否发「暂无关联 CL」。
- 某 CL 在 P4 不存在：该 CL 记入「以下 CL 查询失败」，其余照常汇总。
- 飞书 230002/230006：检查应用权限与机器人是否在群内。

---

## 项目结构

```
jira-p4-feishu/
├── main.py              # 命令行入口（单次执行）
├── jira_watcher.py      # Jira 分配监控常驻进程
├── bot_server_ws.py     # 飞书机器人（长连接）
├── jira_client.py       # Jira API、解析 CL、分配给我查询
├── p4_client.py         # P4 describe、变更解析、项目上下文
├── feishu_client.py     # 飞书 token、发消息、多维表格
├── ai_client.py         # AI 测试范围分析
├── requirements.txt
├── Jenkinsfile.watcher  # Jenkins Pipeline 示例
└── README.md
```
