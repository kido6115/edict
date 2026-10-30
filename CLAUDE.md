# 三省六部 · Edict（Claude Code 版）

用唐代三省六部制组织的多 Agent 协作系统。皇上（用户）下旨 → 太子分拣 → 中书省规划 → 门下省审议 → 尚书省派发 → 六部执行 → 回奏，全程同步到看板。

## 下旨

- `/edict <旨意>`：主会话担任太子，按 `.claude/skills/edict/SKILL.md` 的朝堂规程调用各省部 subagent。
- `/edict JJC-YYYYMMDD-NNN`：从看板当前状态续办该任务。
- `claude --agent taizi`：以太子为主线程启动（适合长期挂着收旨）。

Claude Code 的 subagent 不能再调用 subagent，所以**只有主线程（太子）调度**；中书省、门下省、尚书省、六部都只做本职并把结果交回。

## 目录要点

| 路径 | 说明 |
|------|------|
| `agents.json` | Agent 注册表：id、描述、模型、可用工具 |
| `agents/<id>/SOUL.md`、`agents/GLOBAL.md` | 各省部提示词源文件 |
| `agents/<id>/skills/<name>/SKILL.md` | 各部专属技能（会列入生成的 Agent 定义） |
| `.claude/agents/<id>.md` | **生成文件**，勿手改；改源文件后运行 `python3 scripts/claude_runtime.py build` |
| `.claude/skills/edict/SKILL.md` | 朝堂规程（也会附在太子的 Agent 定义里） |
| `scripts/kanban_update.py` | 看板唯一写入口（create/state/flow/progress/todo/done/confirm） |
| `scripts/claude_runtime.py` | 运行时适配层：生成 Agent 定义、切换模型、headless 调用并记录会话 |
| `dashboard/server.py` | 军机处看板（http://127.0.0.1:7891），派发时调用 `claude -p --agent taizi` |
| `data/` | 运行数据（git 忽略）；会话日志在 `data/runtime/agents/<id>/sessions/` |
| `edict/` | 可选的 Postgres + Redis 事件驱动后端，dispatcher 同样调用 `claude -p --agent <id>` |

## 规则

- 看板只能通过 `python3 scripts/kanban_update.py ...` 修改，不要直接编辑 `data/*.json`。
- 改了 `agents.json`、`SOUL.md`、`GLOBAL.md`、技能或 `edict` 技能后，运行 `python3 scripts/claude_runtime.py build`。
- 切换模型：`python3 scripts/claude_runtime.py model <id> <inherit|sonnet|opus|haiku|模型ID>`，或在看板「模型配置」中操作。

## 看板 headless 派发的环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CLAUDE_BIN` | `claude` | claude CLI 路径（Windows 可指向 `claude.cmd`） |
| `EDICT_CLAUDE_PERMISSION_MODE` | `acceptEdits` | 传给 `--permission-mode`；无人值守时 Bash 命令需在 `.claude/settings.json` 放行 |
| `EDICT_CLAUDE_ARGS` | 空 | 追加给 claude 的参数，如 `--model sonnet --max-budget-usd 5` |
| `EDICT_DISPATCH_AGENT` | `taizi` | 派发时作为主线程的 Agent |
| `EDICT_DISPATCH_TIMEOUT` | `1800` | 单次派发超时（秒），一次派发可能跑完整条流程 |
| `EDICT_RUNTIME_HOME` | `data/runtime` | 会话日志目录 |
| `ANTHROPIC_API_KEY` / `EDICT_LLM_*` | — | 朝堂议政用的 LLM；都没有时回落到 `claude -p` |

建议的 `.claude/settings.json`（让 headless 派发能直接更新看板）：

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 scripts/kanban_update.py:*)",
      "Bash(python3 scripts/refresh_live_data.py:*)",
      "Bash(grep:*)",
      "Bash(date:*)"
    ]
  }
}
```

## 测试

```bash
python3 -m pytest -q tests
```
