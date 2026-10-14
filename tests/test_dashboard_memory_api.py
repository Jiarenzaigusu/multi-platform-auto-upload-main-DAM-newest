"""Exercise the real authentication/CSRF stack without any live model calls."""
from contextlib import closing
import unittest
from unittest.mock import patch

import tests.test_auth_multi_user as auth_tests
from webapp.dashboard_agent import ConversationStore
from webapp.dashboard_memory import BrandMemoryService, BrandProfile, MemoryEntry


class MemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = auth_tests.MultiUserApiTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.brand = patch('webapp.api.main.resolve_data_brand', return_value={'id': 7, 'name': '品牌A'})
        self.brand.start()

    def tearDown(self):
        self.brand.stop()
        self.fixture.tearDown()

    def prepare(self):
        user = self.fixture.bootstrap_admin()
        workspace = self.fixture.registry.get(user['id'])
        # Deterministic worker: all extraction here is local and explicitly driven.
        workspace._dashboard_memory = BrandMemoryService(workspace.paths.runtime / 'dashboard-chat.sqlite3', workspace.llm_registry, start=False)
        store = workspace.dashboard_memory.store
        chat = ConversationStore(store.path)
        cid, _ = chat.open(7, '2026-10', 'image', 'all')
        ids = chat.append(cid, '以后优先看点击', '好', [], learn=True)
        with closing(store.connect()) as db, db:
            db.execute('UPDATE brand_memory_jobs SET available_at=0')
        job = store.claim()
        proposal = MemoryEntry(kind='rule', key='ranking', value='点击优先', source_message_id=ids['user_message_id'], source_quote='以后优先看点击')
        store.finish(job, store.profile(7), BrandProfile(entries=[proposal]), 'test')
        return store, store.profile(7)['entries'][0]['id']

    def test_login_csrf_edit_conflict_revoke_and_rollback(self):
        self.assertEqual(self.client.get('/api/dashboard/memory').status_code, 401)
        store, item = self.prepare()
        self.assertEqual(self.client.get('/api/dashboard/memory').json()['entries'][0]['value'], '点击优先')
        body = {'version': 1, 'value': '商品点击优先'}
        path = f'/api/dashboard/memory/items/{item}'
        self.assertEqual(self.client.patch(path, json=body).status_code, 403)
        response = self.client.patch(path, json=body, headers=self.fixture.csrf_headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 2)
        stale = self.client.patch(path, json=body, headers=self.fixture.csrf_headers())
        self.assertEqual(stale.status_code, 409)
        removed = self.client.request('DELETE', path, json_body={'version': 2}, headers=self.fixture.csrf_headers())
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(store.context(7, '2026-10', 'image', 'all'), [])
        history = self.client.get('/api/dashboard/memory/revisions').json()
        self.assertEqual(history['version'], 3)
        restored = self.client.post('/api/dashboard/memory/rollback', json={'version': 3, 'target_version': 2}, headers=self.fixture.csrf_headers())
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['version'], 4)

    def test_browser_cannot_select_another_brand_or_edit_its_item(self):
        store, item = self.prepare()
        with patch('webapp.api.main.resolve_data_brand', return_value={'id': 8, 'name': '品牌B'}):
            response = self.client.get('/api/dashboard/memory?brand_id=7')
            self.assertEqual(response.json()['brand_id'], 8)
            self.assertEqual(response.json()['entries'], [])
            forbidden = self.client.patch(f'/api/dashboard/memory/items/{item}', json={'version': 0, 'value': '错误'}, headers=self.fixture.csrf_headers())
            self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(store.profile(7)['entries'][0]['value'], '点击优先')

    def test_same_brand_other_user_has_separate_profile(self):
        self.prepare()
        self.fixture.create_user('operator')
        self.fixture.login('operator', 'operator-password-123')
        response = self.client.get('/api/dashboard/memory')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['entries'], [])

    def test_chat_enqueues_long_term_learning_and_keeps_short_term(self):
        store, _ = self.prepare()
        dashboard = {'brand': {'id': 7, 'name': '品牌A'}, 'selected_period': '2026-10', 'tags': {'image': []}}
        with patch('webapp.api.main.DashboardRepository.load', return_value=dashboard), patch.object(self.fixture.app.state.mysql_database.__class__, 'configured', new_callable=property, fget=lambda _: True), patch('webapp.api.main.answer_question', return_value=('回答', [])) as answer:
            response = self.client.post('/api/dashboard/chat', json={'question': '继续分析', 'period': '2026-10'}, headers=self.fixture.csrf_headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(answer.call_args.kwargs['memory'][0]['value'], '点击优先')
        self.assertEqual(answer.call_args.args[2][-1]['content'], '好')
        self.assertEqual(response.json()['memory_used'][0]['value'], '点击优先')
        with closing(store.connect()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM brand_memory_jobs WHERE state='pending'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
