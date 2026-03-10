# 本机启动 Cursor 的 OpenAI 兼容代理（完整步骤）

使用 [cursor-api-proxy](https://github.com/anyrobert/cursor-api-proxy)，在本地暴露 `http://127.0.0.1:8765/v1`，供 jira-p4-feishu 的「测试范围」AI 调用。

---

## 一、前置条件

1. **Node.js 18+**  
   - 若未安装：到 [nodejs.org](https://nodejs.org/) 下载 LTS，或 `winget install OpenJS.NodeJS.LTS`。
2. **Git**（用于克隆仓库）  
   - Windows 通常已带或可从 [git-scm.com](https://git-scm.com/) 安装。

---

## 二、安装并登录 Cursor CLI（agent）

代理底层通过 Cursor 的 `agent` 调用模型，必须先装好并登录。

### Windows（PowerShell）

```powershell
# 安装 Cursor CLI
irm 'https://cursor.com/install?win32=true' | iex

# 关闭并重新打开一个 PowerShell，然后登录（会打开浏览器）
agent login

# 确认可用模型
agent --list-models
```

### macOS / Linux / WSL

```bash
curl https://cursor.com/install -fsS | bash
# 新开终端
agent login
agent --list-models
```

- **自动化/无头环境**：可设置环境变量 `CURSOR_API_KEY` 代替 `agent login`（需在 Cursor 账号中生成 API Key，见官方文档）。

### 故障排查：agent 找不到（Windows）

若在 PowerShell 中执行 `agent` 报错「无法将“agent”项识别为 cmdlet、函数、脚本文件或可运行程序的名称」：

1. **先执行安装（若未执行过）**  
   在**以管理员身份运行**的 PowerShell 中执行：
   ```powershell
   irm 'https://cursor.com/install?win32=true' | iex
   ```

2. **关闭当前 PowerShell，重新打开一个新的窗口**  
   安装脚本会更新用户 PATH，只有新开的终端才会生效。

3. **在新终端中测试**  
   ```powershell
   agent --version
   ```
   若仍报错，继续下一步。

4. **查找 agent 所在目录并加入 PATH**  
   常见位置（按顺序在资源管理器中查看）：
   - `%USERPROFILE%\.local\bin`（若存在 `agent.exe` 或 `agent.cmd`）
   - `%LOCALAPPDATA%\Programs\cursor\` 或 `%USERPROFILE%\AppData\Local\Programs\cursor\`
   
   在 PowerShell 中搜索：
   ```powershell
   Get-ChildItem -Path $env:USERPROFILE -Recurse -Filter "agent*" -ErrorAction SilentlyContinue | Where-Object { $_.Extension -match "\.(exe|cmd)$" }
   ```
   找到后，将该目录加入用户环境变量 PATH，或每次启动代理前执行：
   ```powershell
   $env:Path += ";<agent所在目录的完整路径>"
   ```

5. **替代方案：不依赖 agent 命令**  
   若无法使用 `agent`，可改用 Cursor 的 API Key（在 Cursor 设置/账号中生成），在启动 cursor-api-proxy 前设置：
   ```powershell
   $env:CURSOR_API_KEY = "你的API Key"
   npm start
   ```
   这样代理可直接用 API Key 调用，无需执行 `agent login`。

---

## 三、安装并构建 cursor-api-proxy

在任意目录执行（以下以 `D:\tools` 为例，可改成你的目录）：

### Windows（PowerShell 或 CMD）

```powershell
cd D:\tools
git clone https://github.com/anyrobert/cursor-api-proxy.git
cd cursor-api-proxy
npm install
npm run build
```

### macOS / Linux / WSL

```bash
cd ~/tools
git clone https://github.com/anyrobert/cursor-api-proxy.git
cd cursor-api-proxy
npm install
npm run build
```

无报错即表示安装与构建成功。

---

## 四、启动代理

在 **cursor-api-proxy** 目录下执行：

```bash
npm start
```

或：

```bash
node dist/cli.js
```

- 默认监听：**http://127.0.0.1:8765**
- 我们的项目请求的是 **http://127.0.0.1:8765/v1**（即 `base_url` 填 `http://127.0.0.1:8765/v1`）。

看到类似 “listening on 127.0.0.1:8765” 的提示即表示代理已就绪。

---

## 五、可选：环境变量

在启动前可设置（非必须）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CURSOR_BRIDGE_HOST` | `127.0.0.1` | 绑定地址 |
| `CURSOR_BRIDGE_PORT` | `8765` | 端口 |
| `CURSOR_BRIDGE_API_KEY` | — | 若设置，请求需带 `Authorization: Bearer <key>` |
| `CURSOR_API_KEY` | — | 无头/自动化时替代 `agent login` |

例如指定端口后再启动：

```powershell
# Windows PowerShell
$env:CURSOR_BRIDGE_PORT = "8766"
npm start
```

```bash
# Linux/macOS
export CURSOR_BRIDGE_PORT=8766
npm start
```

若改端口，config.json 里 `ai.base_url` 也要改成对应端口，例如 `http://127.0.0.1:8766/v1`。

---

## 六、验证代理是否正常

1. **健康检查**  
   浏览器或 curl 访问：  
   `http://127.0.0.1:8765/health`  
   应返回一段 JSON。

2. **查看模型列表**  
   `GET http://127.0.0.1:8765/v1/models`  
   或在 PowerShell：  
   `Invoke-RestMethod -Uri "http://127.0.0.1:8765/v1/models"`  
   会返回可用模型，可与 `agent --list-models` 对照。

3. **本项目的 config.json**  
   确认 `ai` 配置为 Cursor 并指向该代理，例如：

   ```json
   "ai": {
     "api_key": "cursor-local",
     "provider": "cursor",
     "base_url": "http://127.0.0.1:8765/v1",
     "model": "cursor-default"
   }
   ```

   - 若代理设置了 `CURSOR_BRIDGE_API_KEY`，则 `api_key` 填该值。
   - `model` 可填 `cursor-default` 或 `/v1/models` 返回的某个模型 id。

---

## 七、保持代理常驻（可选）

- **Windows**：可把 `npm start` 做成计划任务或用 NSSM 注册为服务，开机/登录后自动启动。
- **Linux/macOS**：用 systemd 或 screen/tmux 在后台跑 `npm start`。

代理需在本机（或 jira-p4-feishu 所在机器）长期运行，`main.py` / Watcher 才能正常调用 Cursor 生成测试范围。

---

## 八、故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `agent: command not found` | Cursor CLI 未装或未加入 PATH | 重新执行安装命令，新开终端，或使用安装目录下的 `agent` 绝对路径 |
| `agent login` 失败 | 网络或账号问题 | 检查网络、重试，或配置 `CURSOR_API_KEY` |
| `npm start` 报错端口占用 | 8765 已被占用 | 换端口：设 `CURSOR_BRIDGE_PORT` 并同步改 config 的 `base_url` |
| 项目请求代理超时 | 代理未启动或防火墙拦截 | 确认代理已 `npm start`，且本机访问 `http://127.0.0.1:8765/health` 正常 |
| 返回 401 | 代理启用了 `CURSOR_BRIDGE_API_KEY` | 在 config.json 的 `ai.api_key` 填同一 key |

完成以上步骤后，本机就已在 8765 端口运行 Cursor 的 OpenAI 兼容代理，jira-p4-feishu 的 AI 测试范围会通过该代理使用 Cursor 模型。
