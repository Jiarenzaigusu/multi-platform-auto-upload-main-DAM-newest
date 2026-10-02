"""Brand-scoped dashboard chat with fixed, read-only data tools."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from webapp.dashboard import _number
from webapp.llm_adapter.provider import ChatProvider
from webapp.mysql_demo import MySQLDatabase


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    period: str = Field(pattern=r'^\d{4}-\d{2}$')
    content_type: Literal['image', 'video'] = 'image'
    tag_id: str = Field(default='all', max_length=200)
    conversation_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')


class ConversationStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(self._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, brand_id INTEGER NOT NULL, period TEXT NOT NULL,
                    content_type TEXT NOT NULL, tag_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
            ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def open(self, brand_id: int, period: str, content_type: str, tag_id: str, conversation_id: str | None = None) -> tuple[str, list[dict]]:
        with closing(self._connect()) as db, db:
            if conversation_id:
                row = db.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
                if not row or (row['brand_id'], row['period'], row['content_type'], row['tag_id']) != (brand_id, period, content_type, tag_id):
                    raise ValueError('会话与当前品牌或分析范围不匹配')
            else:
                row = db.execute('SELECT * FROM conversations WHERE brand_id = ? AND period = ? AND content_type = ? AND tag_id = ? ORDER BY updated_at DESC LIMIT 1', (brand_id, period, content_type, tag_id)).fetchone()
                conversation_id = row['id'] if row else uuid.uuid4().hex
                if not row:
                    db.execute('INSERT INTO conversations(id,brand_id,period,content_type,tag_id) VALUES(?,?,?,?,?)', (conversation_id, brand_id, period, content_type, tag_id))
            messages = [dict(item) for item in db.execute('SELECT role,content,evidence FROM messages WHERE conversation_id = ? ORDER BY id', (conversation_id,))]
            for item in messages:
                item['evidence'] = json.loads(item['evidence'])
            return conversation_id, messages

    def append(self, conversation_id: str, question: str, answer: str, evidence: list[dict]) -> None:
        with closing(self._connect()) as db, db:
            db.execute('INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)', (conversation_id, 'user', question))
            db.execute('INSERT INTO messages(conversation_id,role,content,evidence) VALUES(?,?,?,?)', (conversation_id, 'assistant', answer, json.dumps(evidence, ensure_ascii=False)))
            db.execute('UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (conversation_id,))
            db.execute('DELETE FROM messages WHERE conversation_id = ? AND id NOT IN (SELECT id FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 100)', (conversation_id, conversation_id))
            db.execute('DELETE FROM conversations WHERE id NOT IN (SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 30)')
            db.execute('DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)')


TOOLS = [
    {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'additionalProperties': False}}}
    for name, description, properties in [
        ('get_metrics', '查询当前品牌、周期和所选标签的完整汇总指标', {}),
        ('compare_periods', '比较所选范围在当前周期和上一可用周期的指标', {}),
        ('get_categories', '查询当前范围内各内容分类的汇总指标', {}),
        ('rank_contents', '按指定指标查当前范围的领先作品或高曝光低点击作品', {'metric': {'type': 'string', 'enum': ['product_click_users', 'revenue', 'exposure', 'low_click']}}),
        ('get_content_history', '按作品ID查当前品牌中该作品最近的周期数据', {'content_id': {'type': 'string', 'maxLength': 100}}),
    ]
]


class DashboardTools:
    def __init__(self, database: MySQLDatabase, dashboard: dict, content_type: str, tag_id: str):
        self.database = database
        self.dashboard = dashboard
        self.brand_id = dashboard['brand']['id']
        self.period = dashboard['selected_period']
        self.content_type = content_type
        self.tag_id = tag_id
        tags = dashboard['tags'].get(content_type, [])
        if tag_id != 'all' and not any(tag['id'] == tag_id or tag['category'] == tag_id for tag in tags):
            raise ValueError('当前周期不存在所选内容标签')
        self.scope_label = ('全部图文' if content_type == 'image' else '全部视频') if tag_id == 'all' else tag_id

    def _where(self, period: str | None = None) -> tuple[str, tuple]:
        period = period or self.period
        clause = 'brand_id = %s AND `年份` = %s AND `下载周期` = %s'
        args: list[Any] = [self.brand_id, int(period[:4]), f'{int(period[5:])}月']
        if self.content_type == 'image':
            clause += ' AND `汇总分类` = %s'
            args.append('图文')
        else:
            clause += ' AND `汇总分类` <> %s'
            args.append('图文')
        if self.tag_id != 'all':
            if ' · ' in self.tag_id:
                category, subcategory = self.tag_id.split(' · ', 1)
                clause += ' AND `汇总分类` = %s AND `二级分类` = %s'
                args.extend((category, subcategory))
            else:
                clause += ' AND `汇总分类` = %s'
                args.append(self.tag_id)
        return clause, tuple(args)

    def get_metrics(self, period: str | None = None) -> dict:
        where, args = self._where(period)
        row = self.database.execute(f'SELECT COUNT(*), SUM(`查看人数`), SUM(`曝光人数`), SUM(`商品点击人数`), SUM(`种草成交金额`), SUM(`曝光次数`) FROM content_performance WHERE {where}', args)[0]
        return {'period': period or self.period, 'scope': self.scope_label, 'content_count': _number(row[0]), 'content_viewers_sum': _number(row[1]), 'exposure_users_sum': _number(row[2]), 'product_click_users_sum': _number(row[3]), 'revenue': _number(row[4]), 'impressions': _number(row[5])}

    def compare_periods(self) -> dict:
        periods = [item['key'] for item in self.dashboard['periods']]
        index = periods.index(self.period)
        current = self.get_metrics()
        if index + 1 >= len(periods):
            return {'current': current, 'previous': None, 'note': '缺少前一可用下载周期'}
        previous = self.get_metrics(periods[index + 1])
        deltas = {key: (current[key] - previous[key]) / previous[key] if previous[key] else None for key in ('content_count', 'content_viewers_sum', 'exposure_users_sum', 'product_click_users_sum', 'revenue')}
        return {'current': current, 'previous': previous, 'deltas': deltas}

    def get_categories(self) -> list[dict]:
        where, args = self._where()
        rows = self.database.execute(f'SELECT `汇总分类`, `二级分类`, COUNT(*), SUM(`曝光人数`), SUM(`商品点击人数`), SUM(`种草成交金额`) FROM content_performance WHERE {where} GROUP BY `汇总分类`, `二级分类` ORDER BY SUM(`种草成交金额`) DESC LIMIT 30', args)
        return [{'category': str(row[0] or ''), 'subcategory': str(row[1] or ''), 'count': _number(row[2]), 'exposure_users_sum': _number(row[3]), 'product_click_users_sum': _number(row[4]), 'revenue': _number(row[5])} for row in rows[:30]]

    def rank_contents(self, metric: str = 'product_click_users') -> list[dict]:
        columns = {'product_click_users': '`商品点击人数`', 'revenue': '`种草成交金额`', 'exposure': '`曝光人数`', 'low_click': '`曝光人数`'}
        if metric not in columns:
            raise ValueError('不支持的排序指标')
        where, args = self._where()
        order = f'{columns[metric]} DESC'
        if metric == 'low_click':
            where += ' AND `曝光人数` >= 1000'
            order = '(`商品点击人数` / GREATEST(`曝光人数`, 1)) ASC, `曝光人数` DESC'
        rows = self.database.execute(f'SELECT `内容ID`, `内容名称`, `内容发布时间`, `曝光人数`, `商品点击人数`, `种草成交金额` FROM content_performance WHERE {where} ORDER BY {order} LIMIT 10', args)
        return [{'content_id': str(row[0]), 'title': str(row[1] or '')[:200], 'published_at': str(row[2])[:10], 'exposure_users': _number(row[3]), 'product_click_users': _number(row[4]), 'revenue': _number(row[5])} for row in rows]

    def get_content_history(self, content_id: str) -> list[dict]:
        if not content_id or len(content_id) > 100:
            raise ValueError('作品ID无效')
        where, args = self._where()
        allowed = self.database.execute(f'SELECT 1 FROM content_performance WHERE {where} AND `内容ID` = %s LIMIT 1', (*args, content_id))
        if not allowed:
            raise ValueError('作品不在当前分析范围内')
        rows = self.database.execute('SELECT `年份`, `下载周期`, `曝光人数`, `商品点击人数`, `种草成交金额` FROM content_performance WHERE brand_id = %s AND `内容ID` = %s ORDER BY `年份` DESC, CAST(REPLACE(`下载周期`, \'月\', \'\') AS UNSIGNED) DESC LIMIT 12', (self.brand_id, content_id))
        return [{'year': row[0], 'cycle': row[1], 'exposure_users': _number(row[2]), 'product_click_users': _number(row[3]), 'revenue': _number(row[4])} for row in rows]

    def run(self, name: str, arguments: dict) -> Any:
        if name not in {'get_metrics', 'compare_periods', 'get_categories', 'rank_contents', 'get_content_history'}:
            raise ValueError('不支持的数据工具')
        if name == 'rank_contents':
            return self.rank_contents(arguments.get('metric', 'product_click_users'))
        if name == 'get_content_history':
            return self.get_content_history(str(arguments.get('content_id', '')))
        return getattr(self, name)()


def answer_question(provider: ChatProvider, tools: DashboardTools, history: list[dict], question: str) -> tuple[str, list[dict]]:
    messages: list[dict] = [{'role': 'system', 'content': f'''你是品牌内容数据助手。当前固定范围：{tools.dashboard['brand']['name']}，{tools.period} 下载周期，{tools.scope_label}。只用数据工具获得事实；先调用至少一个工具。不要要求或执行任意 SQL，不要改变品牌或范围。数字由工具计算，回答注明口径。汇总人数未跨内容去重，种草成交不等于直接购买归因。原因只能写成待验证假设。没有活动资料或外部来源时，不编造近期促销。引用作品时优先使用工具返回的作品名称，不要只写作品 ID；名称缺失时才使用 ID。回答先给结论，再用最多三个最关键的数字说明依据，通常控制在 250 字以内。不要输出明细表、逐条数据、原始 JSON 或代码块；完整查询结果已放在可展开的“查看数据依据”中。用户明确索要明细时可适当增加数字，但仍应概括优先。'''}]
    messages.extend({'role': item['role'], 'content': item['content'][:4000]} for item in history[-8:])
    messages.append({'role': 'user', 'content': question})
    evidence: list[dict] = []
    with provider.session():
        for _ in range(4):
            reply = provider.chat(messages, tools=TOOLS if len(evidence) < 6 else None, temperature=0.2)
            calls = reply.get('tool_calls') or []
            if not calls:
                answer = str(reply.get('content') or '').strip()
                if evidence and answer:
                    return _name_works(_concise_answer(provider, answer), evidence), evidence
                if not evidence:
                    result = tools.get_metrics()
                    evidence.append({'tool': 'get_metrics', 'result': result})
                    messages.append({'role': 'system', 'content': '必须依据以下程序查询结果回答：' + json.dumps(result, ensure_ascii=False)})
                    continue
                break
            if len(evidence) >= 6:
                messages.append({'role': 'system', 'content': '工具调用次数已用完，请依据已有查询结果直接回答。'})
                continue
            calls = calls[:min(3, 6 - len(evidence))]
            messages.append({'role': 'assistant', 'content': reply.get('content'), 'tool_calls': calls})
            for call in calls:
                function = call.get('function') or {}
                name = str(function.get('name') or '')
                try:
                    arguments = json.loads(function.get('arguments') or '{}')
                    if not isinstance(arguments, dict):
                        raise ValueError('参数必须是对象')
                    result = tools.run(name, arguments)
                    evidence.append({'tool': name, 'result': result})
                except (ValueError, TypeError, KeyError) as exc:
                    result = {'error': str(exc)}
                messages.append({'role': 'tool', 'tool_call_id': call.get('id'), 'content': json.dumps(result, ensure_ascii=False)[:12000]})
    if evidence:
        reply = provider.chat(messages + [{'role': 'system', 'content': '请依据已有工具结果直接回答，不再调用工具。'}], temperature=0.2)
        answer = str(reply.get('content') or '').strip()
        if answer:
            return _name_works(_concise_answer(provider, answer), evidence), evidence
    raise ValueError('数据助手未能生成有效回答，请重试')


def _concise_answer(provider: ChatProvider, answer: str) -> str:
    """Repair unusually long or tabular model output before saving it to the chat."""
    if len(answer) <= 500 and '```' not in answer and not any(line.lstrip().startswith('|') for line in answer.splitlines()):
        return answer
    reply = provider.chat([
        {'role': 'system', 'content': '将下面的分析压缩成面向业务用户的简短中文回答。先给结论，保留 1—3 个最重要的数字和必要口径，最多 300 字。不要表格、逐条明细、JSON、代码块或 Markdown 标题。不要新增事实或推测。完整数据可在“查看数据依据”中展开。'},
        {'role': 'user', 'content': answer[:12000]},
    ], temperature=0.1)
    concise = str(reply.get('content') or '').strip()
    if concise and len(concise) <= 500 and '```' not in concise and not any(line.lstrip().startswith('|') for line in concise.splitlines()):
        return concise
    # Preserve a short readable excerpt if the repair also violates the format.
    excerpt = answer[:500].split('```', 1)[0]
    excerpt = '\n'.join(line for line in excerpt.splitlines() if not line.lstrip().startswith('|')).strip()
    return excerpt.rsplit('。', 1)[0] + '。' if '。' in excerpt else excerpt or '分析结果较长，请查看数据依据后重试。'


def _name_works(answer: str, evidence: list[dict]) -> str:
    """Replace bare ranked-content IDs with verified titles from tool results."""
    for item in evidence:
        if item.get('tool') != 'rank_contents' or not isinstance(item.get('result'), list):
            continue
        for work in item['result']:
            content_id = str(work.get('content_id') or '')
            title = str(work.get('title') or '').strip()
            if content_id and title and title != content_id:
                answer = re.sub(r'(?<!\d)`?' + re.escape(content_id) + r'`?(?!\d)', lambda _: f'《{title}》', answer)
    return answer
