#!/usr/bin/env python3
"""
同步 agents.json（Claude Code Agent 注册表）→ data/agent_config.json，
并重新生成 .claude/agents/*.md。支持自动发现 agents/<id>/skills/ 下的技能。
"""
import json, os, pathlib, datetime, logging
from file_lock import atomic_json_write
import claude_runtime

log = logging.getLogger('sync_agent_config')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# Auto-detect project root (parent of scripts/)
BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'

ID_LABEL = {
    'taizi':    {'label': '太子',   'role': '太子',     'duty': '消息分拣与朝堂调度',  'emoji': '🤴'},
    'zhongshu': {'label': '中书省', 'role': '中书令',   'duty': '起草任务令与优先级',  'emoji': '📜'},
    'menxia':   {'label': '门下省', 'role': '侍中',     'duty': '审议与退回机制',      'emoji': '🔍'},
    'shangshu': {'label': '尚书省', 'role': '尚书令',   'duty': '派单与升级裁决',      'emoji': '📮'},
    'libu':     {'label': '礼部',   'role': '礼部尚书', 'duty': '文档/汇报/规范',      'emoji': '📝'},
    'hubu':     {'label': '户部',   'role': '户部尚书', 'duty': '资源/预算/成本',      'emoji': '💰'},
    'bingbu':   {'label': '兵部',   'role': '兵部尚书', 'duty': '工程实现与架构设计',  'emoji': '⚔️'},
    'xingbu':   {'label': '刑部',   'role': '刑部尚书', 'duty': '合规/审计/红线',      'emoji': '⚖️'},
    'gongbu':   {'label': '工部',   'role': '工部尚书', 'duty': '基础设施与部署运维',  'emoji': '🔧'},
    'libu_hr':  {'label': '吏部',   'role': '吏部尚书', 'duty': '人事/培训/Agent管理',  'emoji': '👔'},
    'zaochao':  {'label': '钦天监', 'role': '朝报官',   'duty': '每日新闻采集与简报',  'emoji': '📰'},
}

# Claude Code subagent frontmatter 中 model 字段可用的取值
KNOWN_MODELS = [
    {'id': 'inherit',           'label': '跟随主会话',       'provider': 'Claude Code'},
    {'id': 'sonnet',            'label': 'Sonnet（最新）',   'provider': 'Anthropic'},
    {'id': 'opus',              'label': 'Opus（最新）',     'provider': 'Anthropic'},
    {'id': 'haiku',             'label': 'Haiku（最新）',    'provider': 'Anthropic'},
    {'id': 'claude-opus-5-5',   'label': 'Claude Opus 5.5',   'provider': 'Anthropic'},
    {'id': 'claude-sonnet-5-5', 'label': 'Claude Sonnet 5.5', 'provider': 'Anthropic'},
    {'id': 'claude-haiku-5-5',  'label': 'Claude Haiku 5.5',  'provider': 'Anthropic'},
    {'id': 'claude-fable-5-1',  'label': 'Claude Fable 5.1',  'provider': 'Anthropic'},
]


def _collect_models(reg):
    """KNOWN_MODELS + agents.json 中出现过的自定义模型 ID。"""
    known_ids = {m['id'] for m in KNOWN_MODELS}
    extra = []
    for m in [reg.get('defaultModel', '')] + [a.get('model', '') for a in reg.get('agents', [])]:
        if m and m not in known_ids:
            extra.append({'id': m, 'label': m, 'provider': 'Custom'})
            known_ids.add(m)
    return KNOWN_MODELS + extra


def main():
    reg = claude_runtime.load_registry()
    default_model = reg.get('defaultModel') or 'inherit'

    result = []
    for ag in reg.get('agents', []):
        ag_id = ag.get('id', '')
        meta = ID_LABEL.get(ag_id)
        if not meta:
            meta = {k: ag.get(k, ag_id) for k in ('label', 'role')}
            meta.update({'duty': ag.get('description', ''), 'emoji': ag.get('emoji', '🏛️')})
        model = ag.get('model') or default_model
        result.append({
            'id': ag_id,
            'label': meta['label'], 'role': meta['role'], 'duty': meta['duty'], 'emoji': meta['emoji'],
            'model': model,
            'defaultModel': default_model,
            'isDefaultModel': model == default_model,
            'workspace': str(claude_runtime.agent_workspace(ag_id)),
            'agentFile': str(claude_runtime.agent_file(ag_id)),
            'skills': claude_runtime.list_agent_skills(ag_id),
            'allowAgents': ag.get('allowAgents', []),
        })

    # 保留已有的 dispatchChannel 配置 (Fix #139)
    existing_cfg = {}
    cfg_path = DATA / 'agent_config.json'
    if cfg_path.exists():
        try:
            existing_cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'runtime': 'claude-code',
        'defaultModel': default_model,
        'knownModels': _collect_models(reg),
        'dispatchChannel': existing_cfg.get('dispatchChannel') or os.getenv('DEFAULT_DISPATCH_CHANNEL', ''),
        'agents': result,
    }
    DATA.mkdir(exist_ok=True)
    atomic_json_write(DATA / 'agent_config.json', payload)
    log.info(f'{len(result)} agents synced')

    # 重新生成 .claude/agents/*.md（SOUL.md / 技能有变化时才写入）
    written = claude_runtime.build()
    if written:
        log.info(f'{len(written)} agent files regenerated')


if __name__ == '__main__':
    main()
