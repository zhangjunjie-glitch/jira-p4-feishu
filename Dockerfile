# Jira-P4-Feishu 常驻进程镜像（默认运行 Jira 分配监控）
FROM python:3.11-slim

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码（配置与敏感信息通过挂载或环境变量注入）
COPY *.py ./

# 默认持续运行 Jira 分配监控；可覆盖 CMD 运行 bot：python bot_server_ws.py
CMD ["python", "-u", "jira_watcher.py"]
