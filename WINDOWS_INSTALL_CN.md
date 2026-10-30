# Windows 安装说明（Claude Code 版）

## 1. 前置条件

- Python 3.10+（安装时勾选 “Add to PATH”）
- Node.js 18+
- Claude Code：`npm install -g @anthropic-ai/claude-code`，然后运行一次 `claude` 完成登录

> 也可以在 WSL 中按 Linux 方式安装（`./install.sh`），体验与 macOS/Linux 一致。

## 2. 安装

```powershell
git clone <你的 fork 地址> edict
cd edict
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

脚本会生成 `.claude\agents\*.md`、初始化 `data\`、构建前端并完成首次同步。

## 3. 使用

**交互式下旨：**

```powershell
cd edict
claude
# 在 Claude Code 中输入：/edict 帮我写一份本周工作周报
```

**看板驱动：**

```powershell
.\scripts\run_loop.ps1          # 数据刷新循环
python dashboard\server.py      # 看板 http://127.0.0.1:7891
```

## 4. 常见问题

- **看板提示“未找到 claude CLI”**：npm 安装的 CLI 在 Windows 上通常是 `claude.cmd`，
  设置环境变量 `CLAUDE_BIN` 指向它，例如
  `setx CLAUDE_BIN "%APPDATA%\npm\claude.cmd"`，然后重开终端。
- **派发后 Agent 无法更新看板**：headless 模式默认 `acceptEdits` 权限，Bash 命令需在
  `.claude\settings.json` 中放行（示例见 `CLAUDE.md`），或设置 `EDICT_CLAUDE_PERMISSION_MODE`。
- **修改了 SOUL.md / agents.json**：运行 `python scripts\claude_runtime.py build` 重新生成 Agent 定义。
