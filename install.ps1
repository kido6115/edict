# ══════════════════════════════════════════════════════════════
# 三省六部 · Claude Code Multi-Agent System 一键安装脚本 (Windows)
# PowerShell 版本 — 对应 install.sh
# ══════════════════════════════════════════════════════════════
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Banner {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Blue
    Write-Host "║  🏛️  三省六部 · Claude Code Multi-Agent ║" -ForegroundColor Blue
    Write-Host "║       安装向导 (Windows)                  ║" -ForegroundColor Blue
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Blue
    Write-Host ""
}

function Log   { param($msg) Write-Host "✅ $msg" -ForegroundColor Green }
function Warn  { param($msg) Write-Host "⚠️  $msg" -ForegroundColor Yellow }
function Error { param($msg) Write-Host "❌ $msg" -ForegroundColor Red }
function Info  { param($msg) Write-Host "ℹ️  $msg" -ForegroundColor Blue }

# ── Step 0: 依赖检查 ──
function Check-Deps {
    Info "检查依赖..."

    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        $py = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if (-not $py) {
        Error "未找到 python3 或 python"
        exit 1
    }
    $global:PYTHON = $py.Source
    Log "Python: $($global:PYTHON)"

    $claudeBin = if ($env:CLAUDE_BIN) { $env:CLAUDE_BIN } else { "claude" }
    $cc = Get-Command $claudeBin -ErrorAction SilentlyContinue
    if ($cc) {
        Log "Claude Code CLI: $($cc.Source)"
    } else {
        Warn "未找到 claude CLI。安装方式: npm install -g @anthropic-ai/claude-code"
        Warn "（未安装也能完成安装，但看板无法自动派发任务；必要时设置 CLAUDE_BIN 指向 claude.cmd）"
    }
}

# ── Step 1: 生成 Claude Code Agent 定义 ──
function Build-Agents {
    Info "生成 .claude\agents\*.md ..."
    Push-Location $REPO_DIR
    & $global:PYTHON scripts/claude_runtime.py build
    Pop-Location
    Log "Agent 定义已就绪"
}

# ── Step 3: 初始化 Data ──
function Init-Data {
    Info "初始化数据目录..."
    $dataDir = Join-Path $REPO_DIR "data"
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

    foreach ($f in @("live_status.json","agent_config.json","model_change_log.json")) {
        $fp = Join-Path $dataDir $f
        if (-not (Test-Path $fp)) { Set-Content $fp "{}" -Encoding UTF8 }
    }
    Set-Content (Join-Path $dataDir "pending_model_changes.json") "[]" -Encoding UTF8
    Log "数据目录初始化完成"
}

# ── Step 3: 构建前端 ──
function Build-Frontend {
    Info "构建 React 前端..."
    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        Warn "未找到 node，跳过前端构建。看板将使用预构建版本（dashboard\dist）"
        return
    }
    $frontend = Join-Path $REPO_DIR "edict\frontend"
    if (Test-Path (Join-Path $frontend "package.json")) {
        Push-Location $frontend
        npm install --silent 2>$null
        npm run build 2>$null
        Pop-Location
        $built = Join-Path $frontend "dist"
        if (Test-Path (Join-Path $built "index.html")) {
            $target = Join-Path $REPO_DIR "dashboard\dist"
            if (Test-Path $target) { Remove-Item $target -Recurse -Force }
            Copy-Item $built $target -Recurse
            Log "前端构建完成: dashboard\dist\"
        } else {
            Warn "前端构建失败，将继续使用预构建版本"
        }
    }
}

# ── Step 4: 首次数据同步 ──
function First-Sync {
    Info "执行首次数据同步..."
    Push-Location $REPO_DIR
    $env:REPO_DIR = $REPO_DIR
    try { & $global:PYTHON scripts/sync_agent_config.py } catch { Warn "sync_agent_config 有警告" }
    try { & $global:PYTHON scripts/sync_officials_stats.py } catch { Warn "sync_officials_stats 有警告" }
    try { & $global:PYTHON scripts/refresh_live_data.py } catch { Warn "refresh_live_data 有警告" }
    Pop-Location
    Log "首次同步完成"
}

# ── Main ──
Write-Banner
Check-Deps
Build-Agents
Init-Data
Build-Frontend
First-Sync

Write-Host ""
Write-Host "🎉 三省六部安装完成！" -ForegroundColor Green
Write-Host ""
Write-Host "使用方式："
Write-Host "  A. 在 Claude Code 中下旨:  cd $REPO_DIR; claude  然后输入  /edict <旨意>"
Write-Host "  B. 看板驱动:  .\scripts\run_loop.ps1  与  python dashboard\server.py"
Write-Host "     打开 http://127.0.0.1:7891"
Write-Host ""
