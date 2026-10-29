from contextlib import closing, nullcontext
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from webapp.dashboard_agent import ConversationStore, DashboardTools, answer_question
from webapp.dashboard_memory import (
    BrandMemoryService, BrandMemoryStore, BrandProfile, MemoryConflict, MemoryEdit,
    MemoryEntry, MemoryRollback, MemoryVersionRequest, extract_profile,
)


class DashboardMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'chat.sqlite3'
        self.chat = ConversationStore(self.path)
        self.store = BrandMemoryStore(self.path)
        self.cid, _ = self.chat.open(7, '2026-10', 'image', 'all')

    def tearDown(self):
        self.temp.cleanup()

    def job(self, question, *, cid=None):
        ids = self.chat.append(cid or self.cid, question, '可能是封面问题。', [], learn=True)
        with closing(self.store.connect()) as db, db:
            db.execute('UPDATE brand_memory_jobs SET available_at=0')
        job = self.store.claim()
        self.assertIsNotNone(job)
        return job, ids['user_message_id']

    def proposal(self, source, quote, *, period=None, value='推荐优先看点击', key='ranking.primary', kind='rule', **kwargs):
        return MemoryEntry(kind=kind, key=key, value=value, period=period, source_message_id=source, source_quote=quote, **kwargs)

    def learn(self, question='以后推荐优先看点击', **kwargs):
        job, source = self.job(question)
        proposal = self.proposal(source, question, **kwargs)
        self.store.finish(job, self.store.profile(7), BrandProfile(entries=[proposal]), 'test-model')
        return self.store.profile(7)

    def test_profile_survives_restart_and_scope_changes(self):
        self.learn()
        reopened = BrandMemoryStore(self.path)
        self.assertEqual(reopened.context(7, '2026-11', 'video', '新品')[0]['value'], '推荐优先看点击')
        self.assertEqual(reopened.context(8, '2026-11', 'image', 'all'), [])
        other = Path(self.temp.name) / 'other-user.sqlite3'
        ConversationStore(other)
        self.assertEqual(BrandMemoryStore(other).profile(7)['entries'], [])

    def test_temporary_override_does_not_destroy_default(self):
        self.learn()
        self.learn('当前周期推荐优先看成交', period='2026-10', value='推荐优先看成交')
        self.assertEqual(len(self.store.profile(7)['entries']), 2)
        self.assertEqual(self.store.context(7, '2026-10', 'image', 'all')[0]['value'], '推荐优先看成交')
        self.assertEqual(self.store.context(7, '2026-11', 'image', 'all')[0]['value'], '推荐优先看点击')

    def test_expired_and_pending_memory_not_used(self):
        self.learn('截至2020年活动以成交为主', expires_on=date(2020, 1, 1))
        self.learn('活动目标尚待确认', key='goal', kind='goal', state='pending')
        self.assertEqual(self.store.context(7, '2026-10', 'image', 'all'), [])

    def test_tag_memory_does_not_bleed_into_other_tag(self):
        tagged, _ = self.chat.open(7, '2026-10', 'video', '新品')
        job, source = self.job('以后新品视频单独比较', cid=tagged)
        p = self.proposal(source, '以后新品视频单独比较', content_type='video', tag_id='新品')
        self.store.finish(job, self.store.profile(7), BrandProfile(entries=[p]), 'test')
        self.assertEqual(len(self.store.context(7, '2026-11', 'video', '新品')), 1)
        self.assertEqual(self.store.context(7, '2026-11', 'video', 'all'), [])

    def test_assistant_source_and_fabricated_quote_rejected(self):
        job, source = self.job('以后看点击')
        for proposed in [self.proposal(source + 1, '可能是封面问题。'), self.proposal(source, '以后看成交')]:
            with self.assertRaises(ValueError):
                self.store.finish(job, self.store.profile(7), BrandProfile(entries=[proposed]), 'test')
        self.assertEqual(self.store.profile(7)['version'], 0)

    def test_guess_and_unbounded_temporary_rule_rejected(self):
        for quote, kind in [('可能是封面问题', 'background'), ('这次优先看成交', 'rule')]:
            job, source = self.job(quote)
            with self.assertRaises(ValueError):
                self.store.finish(job, self.store.profile(7), BrandProfile(entries=[self.proposal(source, quote, kind=kind)]), 'test')
            self.store.fail(job, '测试失败')
            with closing(self.store.connect()) as db, db:
                db.execute("UPDATE brand_memory_jobs SET state='failed'")
        self.assertEqual(self.store.profile(7)['entries'], [])

    def test_goal_needs_scope(self):
        with self.assertRaises(ValueError):
            self.proposal(1, '拉新', kind='goal')

    def test_spoken_month_not_confused_with_dashboard_period(self):
        job, source = self.job('这个月优先看成交')
        next(r for r in job['payload']['messages'] if r['id'] == source)['created_at'] = '2026-11-01 00:00:00'
        with self.assertRaisesRegex(ValueError, '发生月份'):
            self.store.finish(job, self.store.profile(7), BrandProfile(entries=[self.proposal(source, '这个月优先看成交', period='2026-10')]), 'test')

    def test_bridge_rejects_missing_tool_calls(self):
        from webapp.llm_adapter.langmem_model import ProviderChatModel
        provider = MagicMock()
        provider.chat.return_value = {'content': '记住了'}
        with self.assertRaises(ValueError):
            ProviderChatModel(provider=provider).bind_tools([BrandProfile], tool_choice='any').invoke('提取')

    def test_candidate_omission_keeps_old_memory(self):
        self.learn()
        job, _ = self.job('本期有多少作品？')
        self.store.finish(job, self.store.profile(7), BrandProfile(), 'test')
        self.assertEqual(len(self.store.profile(7)['entries']), 1)

    def test_manual_edit_cancels_running_job_and_late_commit(self):
        profile = self.learn()
        job, source = self.job('以后看成交')
        candidate = BrandProfile(entries=[self.proposal(source, '以后看成交', value='成交优先')])
        changed = self.store.edit(7, profile['entries'][0]['id'], MemoryEdit(version=1, value='手动以点击为主'))
        self.assertFalse(self.store.finish(job, profile, candidate, 'test'))
        self.assertEqual(changed['version'], 2)
        self.assertEqual(self.store.context(7, '2026-10', 'image', 'all')[0]['value'], '手动以点击为主')
        with self.assertRaises(MemoryConflict):
            self.store.edit(7, profile['entries'][0]['id'], MemoryEdit(version=1, value='过期修改'))

    def test_revocation_not_resurrected_and_can_be_restored(self):
        profile = self.learn()
        item_id = profile['entries'][0]['id']
        self.store.edit(7, item_id, MemoryVersionRequest(version=1), retract=True)
        self.assertEqual(self.store.context(7, '2026-10', 'image', 'all'), [])
        self.learn()
        self.assertEqual(self.store.context(7, '2026-10', 'image', 'all'), [])
        restored = self.store.edit(7, item_id, MemoryEdit(version=2, value='已恢复的点击要求'))
        self.assertEqual(restored['entries'][0]['state'], 'active')

    def test_rollback_creates_new_version_and_tombstones(self):
        self.learn()
        self.learn('以后最多三条建议', key='answer.length', kind='preference')
        result = self.store.rollback(7, MemoryRollback(version=2, target_version=1))
        self.assertEqual(result['version'], 3)
        self.assertEqual(len(self.store.context(7, '2026-10', 'image', 'all')), 1)
        self.assertTrue(any(e['state'] == 'retracted' for e in result['entries']))
        with self.assertRaises(LookupError):
            self.store.rollback(8, MemoryRollback(version=0, target_version=1))

    def test_job_snapshot_survives_retention_and_bootstrap_is_idempotent(self):
        self.chat.append(self.cid, '以后看点击', '好', [])
        self.store.bootstrap(7)
        self.store.bootstrap(7)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM brand_memory_jobs').fetchone()[0], 1)
        for _ in range(55):
            self.chat.append(self.cid, '还有呢？', '好', [])
        _, retained = self.chat.open(7, '2026-10', 'image', 'all')
        self.assertEqual(len(retained), 100)
        with closing(self.store.connect()) as db:
            payload = json.loads(db.execute('SELECT payload FROM brand_memory_jobs').fetchone()[0])
        self.assertEqual(payload['messages'][0]['content'], '以后看点击')

    def test_enqueue_and_messages_rollback_together(self):
        with patch('webapp.dashboard_agent.enqueue_memory', side_effect=RuntimeError('outbox failed')):
            with self.assertRaises(RuntimeError):
                self.chat.append(self.cid, '以后看点击', '好', [], learn=True)
        self.assertEqual(self.chat.open(7, '2026-10', 'image', 'all')[1], [])

    def test_worker_retry_does_not_log_remote_secrets(self):
        self.job('以后看点击')
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE brand_memory_jobs SET state='pending',attempts=0")
        service = BrandMemoryService(self.path, MagicMock(), start=False)
        with patch('webapp.dashboard_memory.extract_profile', side_effect=RuntimeError('sk-private-secret')):
            self.assertTrue(service.process_one())
        with closing(self.store.connect()) as db:
            row = db.execute('SELECT state,error FROM brand_memory_jobs').fetchone()
        self.assertEqual(row['state'], 'retry')
        self.assertNotIn('secret', row['error'])

    def test_worker_waits_for_adapter_without_consuming_attempts(self):
        self.chat.append(self.cid, '以后看点击', '好', [], learn=True)
        with closing(self.store.connect()) as db, db:
            db.execute('UPDATE brand_memory_jobs SET available_at=0')
        registry = MagicMock()
        registry.snapshot.return_value = None
        service = BrandMemoryService(self.path, registry, start=False)
        self.assertFalse(service.process_one())
        with closing(self.store.connect()) as db:
            row = db.execute('SELECT state,attempts FROM brand_memory_jobs').fetchone()
        self.assertEqual((row['state'], row['attempts']), ('pending', 0))

    def test_claim_lease_recovery_and_brand_serial_order(self):
        self.chat.append(self.cid, '以后看点击', '好', [], learn=True)
        self.chat.append(self.cid, '以后看成交', '好', [], learn=True)
        with closing(self.store.connect()) as db, db:
            db.execute('UPDATE brand_memory_jobs SET available_at=0')
        first = self.store.claim()
        self.assertIsNone(self.store.claim())
        with closing(self.store.connect()) as db, db:
            db.execute('UPDATE brand_memory_jobs SET lease_until=0 WHERE id=?', (first['id'],))
        recovered = self.store.claim()
        self.assertEqual(first['id'], recovered['id'])

    def test_real_langmem_and_bridge_extract_and_patch_existing_profile(self):
        """Use real LangMem/Trustcall, with only the network provider substituted."""
        job, source = self.job('以后推荐优先看点击')
        proposal = self.proposal(source, '以后推荐优先看点击')
        provider = MagicMock()
        provider.session.return_value = nullcontext()

        def respond(messages, **options):
            self.assertEqual(options['tool_choice']['function']['name'], 'PatchDoc')
            self.assertTrue(any(t['function']['name'] == 'PatchDoc' for t in options['tools']))
            return {'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {'name': 'PatchDoc', 'arguments': json.dumps({
                'json_doc_id': 'brand-profile', 'planned_edits': '新增明确要求',
                'patches': [{'op': 'add', 'path': '/entries/-', 'value': proposal.model_dump(mode='json')}],
            }, ensure_ascii=False)}}]}

        provider.chat.side_effect = respond
        candidate = extract_profile(provider, job, self.store.profile(7))
        self.assertEqual(candidate.entries, [proposal])
        self.store.finish(job, self.store.profile(7), candidate, 'test')
        self.assertEqual(self.store.profile(7)['version'], 1)

    def test_short_term_history_and_memory_both_reach_answer_model(self):
        dashboard = {'brand': {'id': 7, 'name': '品牌'}, 'selected_period': '2026-10', 'tags': {'image': []}}
        database = MagicMock()
        database.execute.return_value = [(1, 1, 1, 1, 1, 1)]
        provider = MagicMock()
        provider.session.return_value = nullcontext()
        provider.chat.side_effect = [{'content': '先查询'}, {'content': '查询后回答'}]
        history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)} for i in range(12)]
        answer_question(provider, DashboardTools(database, dashboard, 'image', 'all'), history, '现在呢？', memory=[{'value': '点击优先'}])
        messages = provider.chat.call_args_list[0].args[0]
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('点击优先', messages[1]['content'])
        self.assertEqual([m['content'] for m in messages[2:10]], [str(i) for i in range(4, 12)])
        self.assertEqual(messages[10]['content'], '现在呢？')


if __name__ == '__main__':
    unittest.main()
