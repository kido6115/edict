#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 三省六部 · Claude Code Multi-Agent System 一键安装脚本
# ══════════════════════════════════════════════════════════════
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export REPO_DIR

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

banner() {
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║  🏛️  三省六部 · Claude Code Multi-Agent ║${NC}"
  echo -e "${BLUE}║       安装向导                            ║${NC}"
  echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
  echo ""
}

log()   { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
info()  { echo -e "${BLUE}ℹ️  $1${NC}"; }

# ── Step 0: 依赖检查 ──────────────────────────────────────────
check_deps() {
  info "检查依赖..."

  if ! command -v python3 &>/dev/null; then
    error "未找到 python3"
    exit 1
  fi
  log "Python3: $(python3 --version)"

  CLAUDE="${CLAUDE_BIN:-claude}"
  if command -v "$CLAUDE" &>/dev/null; then
    log "Claude Code CLI: $("$CLAUDE" --version 2>/dev/null || echo 'OK')"
  else
    warn "未找到 claude CLI。安装方式: npm install -g @anthropic-ai/claude-code"
    warn "（未安装也能完成安装，但看板无法自动派发任务）"
  fi
}

# ── Step 1: 生成 Claude Code Agent 定义 ──────────────────────
build_agents() {
  info "生成 .claude/agents/*.md ..."
  cd "$REPO_DIR"
  python3 scripts/claude_runtime.py build
  log "Agent 定义已就绪（共 $(ls "$REPO_DIR/.claude/agents"/*.md 2>/dev/null | wc -l | tr -d ' ') 个）"
}

# ── Step 3: 初始化 Data ─────────────────────────────────────
init_data() {
  info "初始化数据目录..."
  
  mkdir -p "$REPO_DIR/data"
  
  # 初始化空文件
  for f in live_status.json agent_config.json model_change_log.json; do
    if [ ! -f "$REPO_DIR/data/$f" ]; then
      echo '{}' > "$REPO_DIR/data/$f"
    fi
  done
  echo '[]' > "$REPO_DIR/data/pending_model_changes.json"

  # 初始任务文件
  if [ ! -f "$REPO_DIR/data/tasks_source.json" ]; then
    python3 << 'PYEOF'
import json, pathlib
tasks = [
    {
        "id": "JJC-DEMO-001",
        "title": "🎉 系统初始化完成",
        "official": "工部尚书",
        "org": "工部",
        "state": "Done",
        "now": "三省六部系统已就绪",
        "eta": "-",
        "block": "无",
        "output": "",
        "ac": "系统正常运行",
        "flow_log": [
            {"at": "2024-01-01T00:00:00Z", "from": "皇上", "to": "中书省", "remark": "下旨初始化三省六部系统"},
            {"at": "2024-01-01T00:01:00Z", "from": "中书省", "to": "门下省", "remark": "规划方案提交审核"},
            {"at": "2024-01-01T00:02:00Z", "from": "门下省", "to": "尚书省", "remark": "✅ 准奏"},
            {"at": "2024-01-01T00:03:00Z", "from": "尚书省", "to": "工部", "remark": "派发：系统初始化"},
            {"at": "2024-01-01T00:04:00Z", "from": "工部", "to": "尚书省", "remark": "✅ 完成"},
        ]
    }
]
import os
data_dir = pathlib.Path(os.environ.get('REPO_DIR', '.')) / 'data'
data_dir.mkdir(exist_ok=True)
(data_dir / 'tasks_source.json').write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
print('tasks_source.json 已初始化')
PYEOF
  fi

  log "数据目录初始化完成: $REPO_DIR/data"
}

# ── Step 3: 构建前端 ──────────────────────────────────────────
build_frontend() {
  info "构建 React 前端..."

  if ! command -v node &>/dev/null; then
    warn "未找到 node，跳过前端构建。看板将使用预构建版本（dashboard/dist）"
    return
  fi

  if [ -f "$REPO_DIR/edict/frontend/package.json" ]; then
    cd "$REPO_DIR/edict/frontend"
    npm install --silent 2>/dev/null || npm install
    if npm run build 2>/dev/null; then
      rm -rf "$REPO_DIR/dashboard/dist"
      cp -R "$REPO_DIR/edict/frontend/dist" "$REPO_DIR/dashboard/dist"
      log "前端构建完成: dashboard/dist/"
    else
      warn "前端构建失败，将继续使用预构建版本"
    fi
    cd "$REPO_DIR"
  fi
}

# ── Step 4: 首次数据同步 ────────────────────────────────────
first_sync() {
  info "执行首次数据同步..."
  cd "$REPO_DIR"
  
  REPO_DIR="$REPO_DIR" python3 scripts/sync_agent_config.py || warn "sync_agent_config 有警告"
  python3 scripts/sync_officials_stats.py || warn "sync_officials_stats 有警告"
  python3 scripts/refresh_live_data.py || warn "refresh_live_data 有警告"
  
  log "首次同步完成"
}

# ── Main ────────────────────────────────────────────────────
banner
check_deps
build_agents
init_data
build_frontend
first_sync

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🎉  三省六部安装完成！                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "使用方式："
echo "  A. 在 Claude Code 中直接下旨（交互式）："
echo "       cd \"$REPO_DIR\" && claude"
echo "       > /edict 帮我调研三款开源向量数据库并写对比报告"
echo "     或以太子为主线程:  claude --agent taizi"
echo ""
echo "  B. 看板驱动（自动派发）："
echo "       ./start.sh                     # 启动刷新循环 + 看板"
echo "       打开 http://127.0.0.1:7891 下旨"
echo ""
info "看板派发以 headless 模式运行 claude，权限模式默认 acceptEdits，"
info "可用 EDICT_CLAUDE_PERMISSION_MODE / EDICT_CLAUDE_ARGS 调整（见 CLAUDE.md）"
