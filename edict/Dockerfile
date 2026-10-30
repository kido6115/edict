FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 与 Claude Code CLI（dispatcher 以 headless 方式调用 claude -p --agent <id>）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/app \
    CLAUDE_PROJECT_DIR=/app

# 安装 Python 依赖
COPY edict/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 复制后端代码
COPY edict/backend/ /app/

# 复制 Alembic 配置
COPY edict/alembic.ini /app/alembic.ini
COPY edict/migration/ /app/migration/

# Claude Code Agent 定义（由 scripts/claude_runtime.py build 生成）与 Agent 源文件
COPY .claude/ /app/.claude/
COPY agents/ /app/agents/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
