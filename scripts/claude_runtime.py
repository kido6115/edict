#!/usr/bin/env python3
"""
三省六部 · Claude Code 运行时适配层

取代原 OpenClaw 运行时，负责：
  1. 由 agents.json + agents/<id>/SOUL.md + agents/GLOBAL.md 生成 .claude/agents/<id>.md
  2. 读写各 Agent 的模型配置（写回 agents.json 并重新生成）
  3. 以 headless 方式调用 Claude Code（claude -p --agent <id>），
     并把 stream-json 输出落盘为看板可读的会话日志：
       data/runtime/agents/<agent_id>/sessions/sessions.json
       data/runtime/agents/<agent_id>/sessions/<session_id>.jsonl
     子 Agent（parent_tool_use_id 非空）的消息会归档到对应部门名下。

用法:
  python3 scripts/claude_runtime.py build              # 重新生成全部 .claude/agents/*.md
  python3 scripts/claude_runtime.py model <id> <model> # 切换某个 Agent 的模型
  python3 scripts/claude_runtime.py run <id> "<消息>"   # 以该 Agent 为主线程执行一次
  python3 scripts/claude_runtime.py check              # 检查 claude CLI 是否可用
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS_JSON = REPO / 'agents.json'
AGENTS_SRC = REPO / 'agents'
CLAUDE_DIR = REPO / '.claude'
CLAUDE_AGENTS_DIR = CLAUDE_DIR / 'agents'
COURT_SKILL = CLAUDE_DIR / 'skills' / 'edict' / 'SKILL.md'

DEFAULT_PERMISSION_MODE = 'acceptEdits'
_GENERATED_MARK = '<!-- 本文件由 scripts/claude_runtime.py build 生成。请修改 agents.json 或 agents/<id>/SOUL.md 后重新生成。 -->'
_AGENT_TOOL_NAMES = ('Agent', 'Task')


# ── 路径 ──

def runtime_home() -> pathlib.Path:
    """运行时数据根目录（会话日志等），可用 EDICT_RUNTIME_HOME 覆盖。"""
    env = os.environ.get('EDICT_RUNTIME_HOME')
    if env:
        return pathlib.Path(env).expanduser()
    return REPO / 'data' / 'runtime'


def sessions_dir(agent_id: str) -> pathlib.Path:
    return runtime_home() / 'agents' / agent_id / 'sessions'


def agents_root() -> pathlib.Path:
    """各 Agent 源目录的根（默认项目 agents/），可用 EDICT_AGENTS_DIR 覆盖。"""
    env = os.environ.get('EDICT_AGENTS_DIR')
    return pathlib.Path(env).expanduser() if env else AGENTS_SRC


def agent_workspace(agent_id: str) -> pathlib.Path:
    """Agent 的工作目录（存放 SOUL.md 与 skills/）。"""
    return agents_root() / agent_id


def agent_skills_dir(agent_id: str) -> pathlib.Path:
    return agent_workspace(agent_id) / 'skills'


def agent_file(agent_id: str) -> pathlib.Path:
    return CLAUDE_AGENTS_DIR / f'{agent_id}.md'


# ── 注册表 ──

def load_registry() -> dict:
    try:
        reg = json.loads(AGENTS_JSON.read_text(encoding='utf-8'))
    except Exception:
        reg = {}
    if not isinstance(reg, dict):
        reg = {}
    reg.setdefault('defaultModel', 'inherit')
    reg.setdefault('agents', [])
    return reg


def save_registry(reg: dict) -> None:
    tmp = AGENTS_JSON.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, AGENTS_JSON)


def list_agents() -> list[dict]:
    return list(load_registry()['agents'])


def get_agent(agent_id: str) -> dict | None:
    return next((a for a in list_agents() if a.get('id') == agent_id), None)


def get_agent_model(agent_id: str) -> str:
    reg = load_registry()
    ag = next((a for a in reg['agents'] if a.get('id') == agent_id), None)
    return (ag or {}).get('model') or reg['defaultModel']


# ── 生成 .claude/agents/*.md ──

def _strip_frontmatter(text: str) -> str:
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            return text[end + 4:].lstrip('\n')
    return text


def _skill_description(skill_md: pathlib.Path) -> str:
    try:
        text = skill_md.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''
    m = re.search(r'^description:\s*(.+)$', text, re.M)
    if m:
        return m.group(1).strip()[:120]
    for line in _strip_frontmatter(text).splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            return line[:120]
    return ''


def list_agent_skills(agent_id: str) -> list[dict]:
    skills = []
    d = agent_skills_dir(agent_id)
    if d.is_dir():
        for sd in sorted(d.iterdir()):
            md = sd / 'SKILL.md'
            if sd.is_dir():
                skills.append({
                    'name': sd.name,
                    'path': str(md),
                    'exists': md.exists(),
                    'description': _skill_description(md) if md.exists() else '',
                })
    return skills


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def render_agent(entry: dict, reg: dict | None = None) -> str:
    reg = reg or load_registry()
    agent_id = entry['id']
    model = entry.get('model') or reg.get('defaultModel') or 'inherit'

    fm = ['---', f'name: {agent_id}', f'description: {_yaml_str(entry.get("description", entry.get("label", agent_id)))}']
    tools = entry.get('tools') or []
    if tools:
        fm.append(f'tools: {", ".join(tools)}')
    fm.append(f'model: {model}')
    fm.append('---')

    parts = ['\n'.join(fm), _GENERATED_MARK]
    soul = agent_workspace(agent_id) / 'SOUL.md'
    if soul.exists():
        parts.append(soul.read_text(encoding='utf-8').replace('__REPO_DIR__', '.').strip())

    # 太子作为主线程时需要完整的朝堂规程
    if agent_id == 'taizi' and COURT_SKILL.exists():
        parts.append('---\n\n# 附：朝堂规程（edict 技能全文）\n\n'
                     + _strip_frontmatter(COURT_SKILL.read_text(encoding='utf-8')).strip())

    glb = AGENTS_SRC / 'GLOBAL.md'
    if glb.exists():
        parts.append('---\n\n' + glb.read_text(encoding='utf-8').strip())

    skills = [s for s in list_agent_skills(agent_id) if s['exists']]
    if skills:
        rel = lambda p: os.path.relpath(p, REPO)  # noqa: E731
        lines = ['---', '', '## 🧰 本部技能', '', '需要时先用 Read 读取对应 SKILL.md，再按其中说明执行：', '']
        for s in skills:
            lines.append(f'- **{s["name"]}** — {s["description"] or "（无描述）"}：`{rel(s["path"])}`')
        parts.append('\n'.join(lines))

    return '\n\n'.join(parts) + '\n'


def build(agent_ids: list[str] | None = None) -> list[pathlib.Path]:
    reg = load_registry()
    CLAUDE_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in reg['agents']:
        if agent_ids and entry.get('id') not in agent_ids:
            continue
        path = agent_file(entry['id'])
        content = render_agent(entry, reg)
        try:
            old = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            old = None
        if old != content:
            path.write_text(content, encoding='utf-8')
            written.append(path)
    return written


def set_agent_model(agent_id: str, model: str) -> str:
    """设置 Agent 模型，返回旧模型。model 为空或等于默认值时回落到默认。"""
    reg = load_registry()
    entry = next((a for a in reg['agents'] if a.get('id') == agent_id), None)
    if entry is None:
        raise KeyError(f'agent {agent_id} not found in agents.json')
    old = entry.get('model') or reg['defaultModel']
    entry['model'] = model or reg['defaultModel']
    save_registry(reg)
    build([agent_id])
    return old


# ── Claude CLI ──

def resolve_claude_bin() -> str | None:
    """返回 claude CLI 路径。可用 CLAUDE_BIN 指定（Windows 上通常是 claude.cmd）。"""
    configured = os.environ.get('CLAUDE_BIN', '').strip()
    if configured:
        return configured
    return shutil.which('claude')


def cli_available() -> bool:
    return bool(resolve_claude_bin())


def cli_version() -> str:
    bin_ = resolve_claude_bin()
    if not bin_:
        return ''
    try:
        r = subprocess.run([bin_, '--version'], capture_output=True, text=True, timeout=15)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return ''


def build_command(prompt: str, agent_id: str | None = None, claude_bin: str | None = None) -> list[str]:
    cmd = [claude_bin or resolve_claude_bin() or 'claude', '-p', prompt,
           '--output-format', 'stream-json', '--verbose']
    if agent_id:
        cmd += ['--agent', agent_id]
    mode = os.environ.get('EDICT_CLAUDE_PERMISSION_MODE', DEFAULT_PERMISSION_MODE).strip()
    if mode:
        cmd += ['--permission-mode', mode]
    extra = os.environ.get('EDICT_CLAUDE_ARGS', '').strip()
    if extra:
        cmd += shlex.split(extra)
    return cmd


# ── 会话日志 ──

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(str(c.get('text', '')) for c in content if isinstance(c, dict) and c.get('type') == 'text')
    return ''


class SessionRecorder:
    """把 stream-json 事件转写为看板会话格式，按 Agent 分文件记录。"""

    def __init__(self, main_agent: str, label: str = ''):
        self.main_agent = main_agent
        self.label = label
        self.session_id = uuid.uuid4().hex
        self.tool_names: dict[str, str] = {}      # tool_use_id → 工具名
        self.subagents: dict[str, str] = {}       # Agent tool_use_id → subagent_type
        self.usage: dict[str, dict] = {}          # agent_id → token 统计
        self.files: dict[str, pathlib.Path] = {}
        self.result_text = ''
        self.is_error = False

    def _agent_for(self, event: dict) -> str:
        parent = event.get('parent_tool_use_id')
        if parent and parent in self.subagents:
            return self.subagents[parent]
        return self.main_agent

    def _file_for(self, agent_id: str) -> pathlib.Path:
        f = self.files.get(agent_id)
        if f is None:
            d = sessions_dir(agent_id)
            d.mkdir(parents=True, exist_ok=True)
            f = d / f'{self.session_id}.jsonl'
            self.files[agent_id] = f
        return f

    def _write(self, agent_id: str, message: dict) -> None:
        line = json.dumps({'type': 'message', 'timestamp': _now_iso(), 'message': message}, ensure_ascii=False)
        with self._file_for(agent_id).open('a', encoding='utf-8') as fh:
            fh.write(line + '\n')
        self._touch(agent_id)

    def _touch(self, agent_id: str, aborted: bool | None = None) -> None:
        index = sessions_dir(agent_id) / 'sessions.json'
        try:
            data = json.loads(index.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        u = self.usage.get(agent_id, {})
        row = data.get(self.session_id, {})
        row.update({
            'sessionId': self.session_id,
            'sessionFile': str(self._file_for(agent_id)),
            'updatedAt': int(time.time() * 1000),
            'origin': {'label': self.label or f'agent:{agent_id}:dispatch', 'channel': 'claude-code'},
            'inputTokens': u.get('in', 0),
            'outputTokens': u.get('out', 0),
            'cacheRead': u.get('cr', 0),
            'cacheWrite': u.get('cw', 0),
            'totalTokens': u.get('in', 0) + u.get('out', 0),
            'costUsd': round(u.get('cost', 0.0), 6),
        })
        if agent_id != self.main_agent:
            row['origin']['label'] = f'agent:{agent_id}:subagent:{self.main_agent}'
        if aborted is not None:
            row['abortedLastRun'] = aborted
        data[self.session_id] = row
        tmp = index.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, index)

    def _add_usage(self, agent_id: str, usage: dict | None, cost: float = 0.0) -> None:
        if not usage:
            return
        u = self.usage.setdefault(agent_id, {'in': 0, 'out': 0, 'cr': 0, 'cw': 0, 'cost': 0.0})
        u['in'] += int(usage.get('input_tokens') or 0)
        u['out'] += int(usage.get('output_tokens') or 0)
        u['cr'] += int(usage.get('cache_read_input_tokens') or 0)
        u['cw'] += int(usage.get('cache_creation_input_tokens') or 0)
        u['cost'] += float(cost or 0.0)

    def feed(self, event: dict) -> None:
        etype = event.get('type')
        if etype == 'assistant':
            msg = event.get('message') or {}
            agent_id = self._agent_for(event)
            content = msg.get('content') or []
            for c in content:
                if c.get('type') == 'tool_use':
                    self.tool_names[c.get('id', '')] = c.get('name', '')
                    if c.get('name') in _AGENT_TOOL_NAMES:
                        sub = (c.get('input') or {}).get('subagent_type') or ''
                        if sub:
                            self.subagents[c.get('id', '')] = sub
            if agent_id != self.main_agent:
                self._add_usage(agent_id, msg.get('usage'))
            self._write(agent_id, {'role': 'assistant', 'content': content})
        elif etype == 'user':
            msg = event.get('message') or {}
            agent_id = self._agent_for(event)
            content = msg.get('content')
            if isinstance(content, str):
                self._write(agent_id, {'role': 'user', 'content': [{'type': 'text', 'text': content}]})
                return
            for c in content or []:
                if c.get('type') == 'tool_result':
                    tid = c.get('tool_use_id', '')
                    self._write(agent_id, {
                        'role': 'toolResult',
                        'toolName': self.tool_names.get(tid, ''),
                        'content': [{'type': 'text', 'text': _tool_result_text(c.get('content'))[:4000]}],
                        'details': {'exitCode': 1 if c.get('is_error') else 0},
                    })
                elif c.get('type') == 'text':
                    self._write(agent_id, {'role': 'user', 'content': [c]})
        elif etype == 'result':
            self.result_text = event.get('result') or self.result_text
            self.is_error = bool(event.get('is_error'))
            self._add_usage(self.main_agent, event.get('usage'), event.get('total_cost_usd') or 0.0)
            self._touch(self.main_agent)

    def start(self, prompt: str) -> None:
        self._write(self.main_agent, {'role': 'user', 'content': [{'type': 'text', 'text': prompt}]})

    def finish(self, aborted: bool) -> None:
        for agent_id in list(self.files):
            self._touch(agent_id, aborted=aborted if agent_id == self.main_agent else None)


def run_agent(agent_id: str, prompt: str, timeout: int = 300, extra_env: dict | None = None,
              label: str = '') -> dict:
    """以 agent_id 为主线程 headless 执行一次 Claude Code。

    返回 {'returncode', 'stdout'(最终回复), 'stderr', 'sessionId'}。
    """
    claude_bin = resolve_claude_bin()
    if not claude_bin:
        return {'returncode': -1, 'stdout': '', 'stderr': 'claude CLI 未找到：请安装 Claude Code 并加入 PATH，或设置 CLAUDE_BIN',
                'sessionId': ''}
    if not agent_file(agent_id).exists():
        build([agent_id])

    env = os.environ.copy()
    # 不设置 EDICT_AGENT_ID：subagent 会继承环境变量，身份交由 kanban_update.py 按任务状态推断
    env.pop('EDICT_AGENT_ID', None)
    env['EDICT_MAIN_AGENT'] = agent_id
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})

    rec = SessionRecorder(agent_id, label=label)
    rec.start(prompt)
    cmd = build_command(prompt, agent_id=agent_id, claude_bin=claude_bin)
    try:
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError as e:
        return {'returncode': -1, 'stdout': '', 'stderr': f'claude CLI 未找到：{e}', 'sessionId': rec.session_id}

    stderr_chunks: list[str] = []
    err_thread = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read() or ''), daemon=True)
    err_thread.start()

    def _pump():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                rec.feed(json.loads(line))
            except Exception:
                continue

    out_thread = threading.Thread(target=_pump, daemon=True)
    out_thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    out_thread.join(timeout=5)
    err_thread.join(timeout=5)

    returncode = -1 if timed_out else proc.returncode
    if returncode == 0 and rec.is_error:
        returncode = 1
    rec.finish(aborted=returncode != 0)
    stderr = ''.join(stderr_chunks)
    if timed_out:
        stderr = f'TIMEOUT after {timeout}s\n' + stderr
    return {
        'returncode': returncode,
        'stdout': rec.result_text[-5000:],
        'stderr': stderr[-2000:],
        'sessionId': rec.session_id,
    }


def _main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == 'build':
        written = build(argv[1:] or None)
        print(f'✅ 已生成 {len(written)} 个文件' + ''.join(f'\n  {p.relative_to(REPO)}' for p in written))
        return 0
    if cmd == 'model' and len(argv) == 3:
        old = set_agent_model(argv[1], argv[2])
        print(f'✅ {argv[1]}: {old} → {argv[2]}')
        return 0
    if cmd == 'run' and len(argv) >= 3:
        r = run_agent(argv[1], ' '.join(argv[2:]))
        print(r['stdout'])
        if r['returncode'] != 0:
            print(r['stderr'], file=sys.stderr)
        return 0 if r['returncode'] == 0 else 1
    if cmd == 'check':
        b = resolve_claude_bin()
        print(f'claude CLI: {b or "未找到"} {cli_version()}')
        return 0 if b else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
