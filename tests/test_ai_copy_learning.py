"""Copy memory integration tests: real auth, SQLite and providers without network calls."""
from contextlib import closing, nullcontext
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

import tests.test_auth_multi_user as auth_tests
from tests.test_ai_copy import FakeChatProvider
from webapp.ai_copy.contracts import CopyRewriteRequest
from webapp.ai_copy.errors import LLMResponseError
from webapp.ai_copy.history import BrandCopyHistory, CopyHistoryConflict
from webapp.ai_copy.service import count_han_characters
from webapp.ai_copy.learning import CopyLearningEngine


class JsonProvider:
    model = 'test-model'
    provider_label = 'Test'
    ready = True
    def __init__(self, answer=None, error=None, hook=None):
        self.answer, self.error, self.hook = answer, error, hook
        self.calls = []
    session = staticmethod(nullcontext)
    def chat(self, messages, **options):
        self.calls.append(deepcopy(messages))
        if self.hook:
            self.hook()
        if self.error:
            raise self.error
        return {'role': 'assistant', 'content': json.dumps(self.answer, ensure_ascii=False)}


class CopyLearningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = auth_tests.MultiUserApiTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.admin = self.fixture.bootstrap_admin()
        self.operator = self.fixture.create_user('copyoperator')
        self.other = self.fixture.create_user('copyother')
        self.store = self.fixture.app.state.copy_history
        self.brand = self.new_brand('文案独立品牌')
        self.second = self.new_brand('另一品牌')
        self.provider = FakeChatProvider()
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = self.provider

    def tearDown(self):
        self.fixture.tearDown()

    def headers(self, brand=None):
        return {**self.fixture.csrf_headers(), 'X-Copy-Brand': (brand or self.brand)['id']}

    def new_brand(self, name):
        r = self.client.post('/api/ai-copy/brands', json={'name': name}, headers=self.fixture.csrf_headers())
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def generate(self, brand=None, **overrides):
        payload = {'expected_brand_id': (brand or self.brand)['id'], 'selling_point_input_mode': 'manual',
                   'manual_selling_point': '轻盈透气，适合日常通勤', 'style': 'relaxed_natural', 'scene': 'work_commute',
                   'title_max_chars': 15, 'body_max_chars': 31, **overrides}
        r = self.client.post('/api/ai-copy/generate', json=payload, headers=self.headers(brand))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def edit(self, record, text='日常通勤，穿上轻盈自在的日常鞋款'):
        r = self.client.patch('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': record['revision'], 'field': 'title', 'index': 0, 'text': text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def adopt(self, record, title=0, body=0):
        r = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/adopt', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': record['revision'], 'title_index': title, 'body_index': body})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def profile(self, brand=None):
        r = self.client.get('/api/ai-copy/profile', headers=self.headers(brand))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def batch_record(self):
        self.provider.draft = {
            'titles': ['轻盈通勤，穿出自在日常', '周末出游，简约鞋款自然好搭', '日常衣橱，添一双轻盈通勤鞋'],
            'bodies': [FakeChatProvider.default_body, '简约鞋型融入日常搭配，陪伴通勤与周末出行，呈现自在从容的穿着感受。'],
        }
        return self.generate(title_count=3, body_count=2)

    def import_copy(self, record, **changes):
        payload = {'expected_brand_id': self.brand['id'], 'version': record['revision'],
                   'title_index': 0, 'body_index': 0, 'title': record['titles'][0], 'body': record['bodies'][0],
                   'platform': 'tmall', 'content_type': 'video', **changes}
        return self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/imports',
                                headers=self.headers(), json=payload)

    def test_batch_rewrite_maps_indices_atomically_and_replays_without_model_call(self):
        record = self.batch_record()
        answer = {
            'titles': [{'index': i, 'text': f'{text}，轻松搭配', 'reference_chars': 15}
                       for i, text in reversed(list(enumerate(record['titles'])))],
            'bodies': [{'index': i, 'text': text + '陪你走过熟悉街道。', 'reference_chars': 100}
                       for i, text in reversed(list(enumerate(record['bodies'])))],
        }
        provider = JsonProvider(answer)
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
        path = '/api/ai-copy/history/' + record['generation_id'] + '/rewrite-batch'
        payload = {'expected_brand_id': self.brand['id'], 'version': 0, 'target': 'both',
                   'message': '全部自然口语一点，保留区别', 'request_id': 'batch-one'}
        response = self.client.post(path, headers=self.headers(), json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        revised = response.json()
        self.assertEqual(revised['revision'], 1)
        self.assertEqual(revised['titles'], [t + '，轻松搭配' for t in record['titles']])
        self.assertEqual(len(revised['bodies']), 2)
        self.assertEqual(self.client.post(path, headers=self.headers(), json=payload).json(), revised)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.client.post(path, headers=self.headers(), json={**payload, 'message': '不同要求'}).status_code, 409)
        sample = self.import_copy(revised, title_index=2, body_index=1,
                                  title=revised['titles'][2], body=revised['bodies'][1]).json()
        self.assertEqual(sample['initial_title'], record['titles'][2])
        self.assertEqual(sample['initial_body'], record['bodies'][1])
        self.assertEqual(json.loads(sample['feedback'])[0]['applies_to'], ['title', 'body'])
        self.assertEqual(self.profile()['preferences'], [])

    def test_invalid_batch_never_partially_saves(self):
        for problem in ('missing', 'duplicate', 'risk', 'short'):
            with self.subTest(problem=problem):
                self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = self.provider
                record = self.batch_record()
                items = [{'index': i, 'text': text, 'reference_chars': 15} for i, text in enumerate(record['titles'])]
                if problem == 'missing': items.pop()
                if problem == 'duplicate': items[-1]['index'] = 0
                if problem == 'risk': items[-1]['text'] = '保证舒适，通勤穿搭'
                if problem == 'short': items[-1]['text'] = '鞋'
                provider = JsonProvider({'titles': items, 'bodies': []})
                self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
                response = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/rewrite-batch', headers=self.headers(), json={
                    'expected_brand_id': self.brand['id'], 'version': 0, 'target': 'title',
                    'message': '一起改标题', 'request_id': problem})
                self.assertEqual(response.status_code, 502, response.text)
                saved = self.store.detail(self.brand['id'], record['generation_id'])
                self.assertEqual((saved['revision'], saved['titles'], saved['bodies']), (0, record['titles'], record['bodies']))
                self.assertEqual(len(provider.calls), 4)

    def test_title_batch_preserves_bodies_and_links_only_matching_feedback(self):
        record = self.batch_record()
        provider = JsonProvider({'titles': [{'index': i, 'text': text + '，随心出发', 'reference_chars': 20}
                                          for i, text in enumerate(record['titles'])], 'bodies': []})
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
        response = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/rewrite-batch', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'target': 'title', 'message': '标题口语一点', 'request_id': 'titles'})
        self.assertEqual(response.status_code, 200, response.text)
        revised = response.json()
        self.assertEqual(revised['bodies'], record['bodies'])
        self.assertEqual(self.profile()['sample_count'], 0)
        sample = self.import_copy(revised).json()
        self.assertEqual(json.loads(sample['feedback'])[0]['applies_to'], ['title'])

    def test_import_is_idempotent_snapshot_checked_and_does_not_restore_withdrawn_sample(self):
        record = self.generate()
        self.assertEqual(self.import_copy(record, title='另一个标题').status_code, 409)
        response = self.import_copy(record)
        self.assertEqual(response.status_code, 200, response.text)
        sample = response.json()
        self.assertEqual(sample['source'], 'workbench_import')
        self.assertEqual(self.import_copy(record).json()['id'], sample['id'])
        self.assertEqual(self.profile()['sample_count'], 1)
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        self.store.sample_enabled(scope, sample['id'], False, self.profile()['version'])
        self.assertFalse(self.import_copy(record).json()['enabled'])
        self.assertEqual(self.profile()['sample_count'], 0)
        edited = self.edit(record)
        self.assertEqual(self.import_copy(record).status_code, 409)
        self.assertEqual(self.store.adoption(scope, sample['id'])['title'], record['title'])
        self.fixture.login('copyoperator', 'operator-password-123')
        self.assertEqual(self.import_copy(edited).status_code, 403)

    def test_jd_video_only_learns_title_and_filters_body_preferences(self):
        record = self.edit(self.generate())
        self.assertEqual(self.import_copy(record, platform='jd').status_code, 409)
        response = self.import_copy(record, platform='jd', body='')
        self.assertEqual(response.status_code, 200, response.text)
        sample = response.json()
        self.assertEqual((sample['field_scope'], sample['body'], sample['initial_body']), ('title', '', ''))
        self.assertNotIn('body', self.store.generation_context(self.store.profile(self.brand['id']))['examples'][0])
        provider = JsonProvider({'candidates': [
            {'category': 'tone', 'scope': 'body', 'text': '正文自然', 'source_quote': ''},
            {'category': 'tone', 'scope': 'both', 'text': '标题正文自然', 'source_quote': ''},
            {'category': 'tone', 'scope': 'title', 'text': '标题自然', 'source_quote': ''},
        ]})
        self.assertEqual([c['scope'] for c in CopyLearningEngine(provider).extract(sample)], ['title'])
        reopened = BrandCopyHistory(self.store.path)
        self.assertEqual(reopened.profile(self.brand['id'])['samples'][0]['field_scope'], 'title')

    def test_brand_independence_shared_catalog_and_csrf(self):
        with patch('webapp.api.main.resolve_data_brand', side_effect=AssertionError('Must not use data brands')):
            record = self.generate()
            self.assertEqual(record['brand_id'], self.brand['id'])
            self.assertEqual(record['brief']['manual_selling_point'], '轻盈透气，适合日常通勤')
        self.assertFalse(self.fixture.app.state.mysql_database.configured)
        self.assertEqual(self.client.post('/api/ai-copy/brands', json={'name': 'no csrf'}).status_code, 403)
        self.fixture.login('copyoperator', 'operator-password-123')
        self.assertEqual({b['id'] for b in self.client.get('/api/ai-copy/brands').json()['brands']}, {self.brand['id'], self.second['id']})
        self.assertEqual(self.client.get('/api/ai-copy/profile', headers=self.headers(self.second)).status_code, 200)
        created = self.client.post('/api/ai-copy/brands', headers=self.headers(), json={'name': '操作员品牌'})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['created_by'], self.operator['id'])
        self.assertEqual(self.client.patch('/api/ai-copy/brands/' + self.brand['id'], headers=self.headers(), json={'name': '不能更名', 'version': 0}).status_code, 403)
        self.assertEqual(self.client.get('/api/ai-copy/profile').status_code, 422)
        self.assertEqual(self.client.get('/api/ai-copy/history/' + record['generation_id'], headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.patch('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'field': 'title', 'index': 0, 'text': '别人的修改'}).status_code, 403)

    def test_only_explicit_adoption_learns_and_snapshot_is_immutable(self):
        record = self.generate()
        edited = self.edit(record)
        self.assertEqual(self.profile()['sample_count'], 0)
        adopted = self.adopt(edited)
        self.assertEqual(adopted['initial_title'], record['title'])
        self.assertEqual(adopted['title'], edited['title'])
        self.assertEqual(self.adopt(edited)['id'], adopted['id'])
        self.assertEqual(self.profile()['sample_count'], 1)
        self.edit(edited, '另一份尚未采用的标题')
        self.assertEqual(self.profile()['samples'][0]['title'], edited['title'])
        context = self.store.generation_context(self.profile())
        self.assertEqual(context['examples'][0]['title'], edited['title'])
        self.assertNotIn('initial_title', context['examples'][0])
        self.assertEqual(context['guidance'], [])

    def test_unedited_adoption_is_positive_sample_without_inferred_preferences(self):
        adopted = self.adopt(self.generate())
        self.assertEqual(adopted['analysis_status'], 'complete')
        self.assertEqual(self.profile()['sample_count'], 1)
        self.assertEqual(self.profile()['preferences'], [])

    def test_candidates_pair_with_chosen_original_and_product_ids_are_frozen(self):
        self.provider.draft = {'titles': ['轻盈自在，陪你走过日常通勤的时光', '夏日通勤，穿上轻盈自在的日常鞋款'],
                               'bodies': [FakeChatProvider.default_body]}
        record = self.generate(title_count=2)
        adopted = self.adopt(record, title=1)
        self.assertEqual(adopted['initial_title'], record['titles'][1])
        from tests.test_ai_copy import build_selling_point_workbook
        service = self.fixture.registry.get(self.admin['id']).ai_copy_service
        catalog = service.upload_selling_points('卖点.xlsx', build_selling_point_workbook([('SKU-A', '轻盈透气')]))
        self.provider.draft = {'title': FakeChatProvider.default_title, 'body': FakeChatProvider.default_body}
        record = self.generate(selling_point_input_mode='excel', manual_selling_point=None,
                               selling_point_catalog_id=catalog.catalog_id, product_identifiers=['SKU-A'])
        self.assertEqual(record['brief']['product_identifiers'], ['SKU-A'])
        self.assertNotIn('product_search', record['brief'])
        self.assertNotIn('selling_point_catalog_id', record['brief'])

    def test_wrong_brand_wrong_header_stale_version_and_invalid_sample_rejected(self):
        record = self.generate()
        r = self.client.patch('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(self.second), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'field': 'title', 'index': 0, 'text': '跨品牌'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.get('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(self.second)).status_code, 404)
        edited = self.edit(record, '含有123数字的标题')
        r = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/adopt', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': edited['revision'], 'title_index': 0, 'body_index': 0})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.profile()['sample_count'], 0)
        r = self.client.patch('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'field': 'title', 'index': 0, 'text': '过期修改'})
        self.assertEqual(r.status_code, 409)

    def test_rewrite_is_validated_scoped_idempotent_and_keeps_feedback(self):
        record = self.generate()
        provider = JsonProvider({'title': '日常通勤，穿上轻盈自在的日常鞋款', 'body': '不得覆盖正文的模型输出内容。',
                                 'title_max_chars': 15, 'body_max_chars': 10})
        service = self.fixture.registry.get(self.admin['id']).ai_copy_service
        service._provider = provider
        payload = {'expected_brand_id': self.brand['id'], 'version': 0, 'title_index': 0, 'body_index': 0,
                   'target': 'title', 'message': '标题改为日常通勤，正文不动', 'request_id': 'rewrite-one'}
        path = '/api/ai-copy/history/' + record['generation_id'] + '/rewrite'
        r = self.client.post(path, headers=self.headers(), json=payload)
        self.assertEqual(r.status_code, 200, r.text)
        revised = r.json()
        self.assertEqual(revised['body'], record['body'])
        self.assertEqual(revised['revision'], 1)
        again = self.client.post(path, headers=self.headers(), json=payload)
        self.assertEqual(again.json()['revision'], 1)
        self.assertEqual(len(provider.calls), 1)
        conflicting = self.client.post(path, headers=self.headers(), json={**payload, 'message': '不同要求'})
        self.assertEqual(conflicting.status_code, 409)
        adopted = self.adopt(revised)
        self.assertEqual(json.loads(adopted['feedback'])[0]['input'], payload['message'])
        self.assertEqual(self.profile()['preferences'], [])

    def test_rewrite_validation_failure_preserves_original(self):
        record = self.generate()
        provider = JsonProvider({'title': '含有123数字标题', 'body': record['body'], 'title_max_chars': 15, 'body_max_chars': 31})
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
        r = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/rewrite', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'title_index': 0, 'body_index': 0,
            'target': 'title', 'message': '修改标题', 'request_id': 'bad'})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(self.store.detail(self.brand['id'], record['generation_id'])['revision'], 0)

    def test_rewrite_accepts_length_variation_and_saves_adoptable_result(self):
        record = self.generate()
        provider = JsonProvider({
            'title': '日常通勤，穿上轻盈自在又好搭的鞋款',
            'body': record['body'].replace('都自然舒展', '自然舒展'),
            'title_max_chars': 15, 'body_max_chars': 31,
        })
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
        response = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/rewrite', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'title_index': 0, 'body_index': 0,
            'target': 'both', 'message': '表达自然完整，不必逐字凑数', 'request_id': 'soft-length'})
        self.assertEqual(response.status_code, 200, response.text)
        revised = response.json()
        self.assertEqual([count_han_characters(revised[field]) for field in ('title', 'body')], [16, 30])
        self.assertEqual(revised['candidate_briefs']['title:0']['title_max_chars'], 15)
        self.assertEqual(revised['candidate_briefs']['body:0']['body_max_chars'], 31)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(revised['revision'], 1)
        adopted = self.adopt(revised)
        self.assertEqual(adopted['title'], revised['title'])
        self.assertEqual(adopted['body'], revised['body'])

    def test_rewrite_still_rejects_invalid_basic_length(self):
        record = self.generate()
        provider = JsonProvider({'title': '鞋', 'body': record['body'], 'title_max_chars': 15, 'body_max_chars': 31})
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = provider
        response = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/rewrite', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'title_index': 0, 'body_index': 0,
            'target': 'title', 'message': '修改标题', 'request_id': 'too-short'})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(self.store.detail(self.brand['id'], record['generation_id'])['revision'], 0)

    def test_analysis_failure_retry_confirmation_scope_conflict_and_withdrawal(self):
        adopted = self.adopt(self.edit(self.generate()))
        service = self.fixture.registry.get(self.admin['id']).ai_copy_service
        service._provider = JsonProvider(error=LLMResponseError('temporary failure'))
        path = '/api/ai-copy/adoptions/' + adopted['id'] + '/analyze'
        r = self.client.post(path, headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['analysis_status'], 'failed')
        self.assertEqual(self.profile()['sample_count'], 1)
        provider = JsonProvider({'candidates': [{'category': 'tone', 'scope': 'title', 'text': '标题更自然', 'source_quote': ''}]})
        service._provider = provider
        self.assertEqual(self.client.post(path, headers=self.headers()).json()['analysis_status'], 'complete')
        self.client.post(path, headers=self.headers())
        self.assertEqual(len(provider.calls), 1)
        profile = self.profile()
        item = profile['preferences'][0]
        self.assertEqual(item['status'], 'pending')
        self.assertEqual(self.store.generation_context(profile)['guidance'], [])
        self.fixture.login('copyoperator', 'operator-password-123')
        self.assertEqual(self.profile()['sample_count'], 1)
        activated = self.client.patch('/api/ai-copy/preferences/' + item['id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': profile['version'], 'status': 'active', 'text': '标题表达自然，减少口号'})
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(self.store.generation_context(activated.json())['guidance'][0]['text'], '标题表达自然，减少口号')
        unrelated = self.store.profile(self.brand['id'], {'scene': 'fitness', 'style': 'relaxed_natural', 'custom_scene': None, 'custom_style': None})
        self.assertEqual(self.store.generation_context(unrelated)['guidance'], [])
        self.assertEqual(self.store.profile(self.second['id'])['sample_count'], 0)
        stale = self.client.patch('/api/ai-copy/preferences/' + item['id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': profile['version'], 'status': 'disabled'})
        self.assertEqual(stale.status_code, 409)
        forbidden = self.client.patch('/api/ai-copy/adoptions/' + adopted['id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': activated.json()['version'], 'enabled': False})
        self.assertEqual(forbidden.status_code, 403)
        self.fixture.login('admin', 'admin-password-123')
        withdrawn = self.client.patch('/api/ai-copy/adoptions/' + adopted['id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': self.profile()['version'], 'enabled': False})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        self.assertEqual(withdrawn.json()['sample_count'], 0)
        self.assertEqual(self.store.generation_context(withdrawn.json())['guidance'], [])

    def test_nonexistent_evidence_cannot_become_candidate(self):
        adopted = self.adopt(self.edit(self.generate()))
        self.fixture.registry.get(self.admin['id']).ai_copy_service._provider = JsonProvider({'candidates': [
            {'category': 'tone', 'scope': 'title', 'text': '自然表达', 'source_quote': '用户从未说过的话'}]})
        r = self.client.post('/api/ai-copy/adoptions/' + adopted['id'] + '/analyze', headers=self.headers())
        self.assertEqual(r.json()['analysis_status'], 'failed')
        self.assertEqual(self.profile()['preferences'], [])

    def test_brand_disabled_while_generating_does_not_save(self):
        self.fixture.login('copyoperator', 'operator-password-123')
        service = self.fixture.registry.get(self.operator['id']).ai_copy_service
        provider = FakeChatProvider()
        original_chat = provider.chat
        def revoke(*args, **kwargs):
            with closing(self.store.connect()) as db, db:
                db.execute('UPDATE copy_brands SET enabled=0,version=version+1 WHERE id=?', (self.brand['id'],))
            return original_chat(*args, **kwargs)
        provider.chat = revoke
        service._provider = provider
        r = self.client.post('/api/ai-copy/generate', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'selling_point_input_mode': 'manual', 'manual_selling_point': '轻盈透气',
            'style': 'relaxed_natural', 'scene': 'work_commute', 'title_max_chars': 15, 'body_max_chars': 31})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(self.store.history(self.brand['id']), [])

    def test_legacy_data_brand_records_are_not_silently_reassigned(self):
        with closing(self.store.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS copy_profiles(brand_id INTEGER PRIMARY KEY,guidance TEXT)')
            db.execute('INSERT INTO copy_profiles VALUES(7,?)', ('旧数据品牌偏好',))
        reopened = BrandCopyHistory(self.store.path)
        self.assertEqual(reopened.profile(self.brand['id'])['preferences'], [])
        with closing(reopened.connect()) as db:
            self.assertEqual(db.execute('SELECT guidance FROM copy_profiles WHERE brand_id=7').fetchone()[0], '旧数据品牌偏好')

    def test_concurrent_analysis_lease_and_old_result_cannot_overwrite(self):
        adopted = self.adopt(self.edit(self.generate()))
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        first, claimed = self.store.claim_analysis(scope, adopted['id'])
        self.assertTrue(claimed)
        _, claimed = self.store.claim_analysis(scope, adopted['id'])
        self.assertFalse(claimed)
        with closing(self.store.connect()) as db, db:
            db.execute('UPDATE copy_adoptions SET analysis_started=0 WHERE id=?', (adopted['id'],))
        second, claimed = self.store.claim_analysis(scope, adopted['id'])
        self.assertTrue(claimed)
        candidate = {'category': 'tone', 'scope': 'title', 'text': '自然表达', 'source_quote': ''}
        self.store.analysis_result(scope, adopted['id'], [candidate], token=first['analysis_token'])
        self.assertEqual(self.profile()['preferences'], [])
        self.store.analysis_result(scope, adopted['id'], [candidate], token=second['analysis_token'])
        self.assertEqual(len(self.profile()['preferences']), 1)

    def test_conflicting_shared_preferences_need_explicit_replacement(self):
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        for text in ('标题自然口语', '标题正式严谨'):
            adopted = self.adopt(self.edit(self.generate()))
            self.store.analysis_result(scope, adopted['id'], [{'category': 'tone', 'scope': 'title', 'text': text, 'source_quote': ''}])
        items = self.profile()['preferences']
        self.store.preference(scope, items[0]['id'], 'active', self.profile()['version'])
        with self.assertRaises(CopyHistoryConflict):
            self.store.preference(scope, items[1]['id'], 'active', self.profile()['version'])
        self.store.preference(scope, items[0]['id'], 'disabled', self.profile()['version'])
        self.store.preference(scope, items[1]['id'], 'active', self.profile()['version'], scope_mode='brand')
        unrelated = self.store.profile(self.brand['id'], {'scene': 'fitness', 'style': 'sweet_cute'})
        self.assertEqual(len(self.store.generation_context(unrelated)['guidance']), 1)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM copy_preference_events').fetchone()[0], 3)

    def test_generation_uses_adopted_sample_and_confirmed_rule_only(self):
        adopted = self.adopt(self.edit(self.generate()))
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        self.store.analysis_result(scope, adopted['id'], [{'category': 'tone', 'scope': 'title', 'text': '减少口号式标题', 'source_quote': ''}])
        item = self.profile()['preferences'][0]
        self.generate()
        self.assertNotIn('减少口号式标题', str(self.provider.calls[-1]['messages']))
        self.store.preference(scope, item['id'], 'active', self.profile()['version'])
        self.generate()
        messages = self.provider.calls[-1]['messages']
        self.assertIn('减少口号式标题', str(messages))
        self.assertIn(adopted['title'], str(messages))
        self.generate(self.second)
        self.assertNotIn('减少口号式标题', str(self.provider.calls[-1]['messages']))
        self.assertNotIn(adopted['title'], str(self.provider.calls[-1]['messages']))

    def test_disabled_brand_is_not_selectable(self):
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        self.store.save_brand(self.admin['id'], self.brand['name'], brand_id=self.brand['id'], version=0, enabled=False)
        self.assertEqual(self.client.get('/api/ai-copy/profile', headers=self.headers()).status_code, 403)
        self.fixture.login('copyoperator', 'operator-password-123')
        self.assertEqual([b['id'] for b in self.client.get('/api/ai-copy/brands').json()['brands']], [self.second['id']])
        self.assertEqual(self.client.get('/api/ai-copy/profile', headers=self.headers()).status_code, 403)

    def test_adoption_rejects_stale_revision_and_re_adoption_restores_sample(self):
        record = self.generate()
        edited = self.edit(record)
        r = self.client.post('/api/ai-copy/history/' + record['generation_id'] + '/adopt', headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'title_index': 0, 'body_index': 0})
        self.assertEqual(r.status_code, 409)
        adopted = self.adopt(edited)
        scope = self.store.scope(self.admin['id'], self.brand['id'], True)
        self.store.sample_enabled(scope, adopted['id'], False, self.profile()['version'])
        self.assertEqual(self.profile()['sample_count'], 0)
        self.adopt(edited)
        self.assertEqual(self.profile()['sample_count'], 1)

    def test_feedback_for_other_candidates_is_not_used_as_quote_evidence(self):
        adopted = self.adopt(self.edit(self.generate()))
        adopted['feedback'] = json.dumps([{'input': '标题口语一点', 'applies_to': ['title']}])
        provider = JsonProvider({'candidates': [{'category': 'tone', 'scope': 'body', 'text': '正文口语化', 'source_quote': '口语一点'}]})
        with self.assertRaises(LLMResponseError):
            CopyLearningEngine(provider).extract(adopted)
        provider.answer = {'candidates': [{'category': 'tone', 'scope': 'body', 'text': '正文口语化', 'source_quote': ''}]}
        self.assertEqual(CopyLearningEngine(provider).extract(adopted), [])

    def test_rewrite_title_preserves_unfinished_short_manual_body(self):
        record = self.generate()
        response = self.client.patch('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(), json={
            'expected_brand_id': self.brand['id'], 'version': 0, 'field': 'body', 'index': 0, 'text': '草稿'})
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()
        provider = JsonProvider({'title': '日常通勤，穿上轻盈自在的日常鞋款', 'body': '草稿', 'title_max_chars': 15, 'body_max_chars': 31})
        payload = CopyRewriteRequest(expected_brand_id=self.brand['id'], version=1, title_index=0, body_index=0,
                                     target='title', message='只改标题', request_id='partial')
        revised = CopyLearningEngine(provider).revise(record, payload, {})
        self.assertEqual(revised['body'], '草稿')

    def test_operator_created_brand_is_shared_with_other_accounts_and_survives_reopen(self):
        self.fixture.login('copyoperator', 'operator-password-123')
        created = self.new_brand('普通用户创建品牌')
        self.fixture.registry.get(self.operator['id']).ai_copy_service._provider = FakeChatProvider()
        record = self.generate(created)
        self.assertEqual(record['owner_id'], self.operator['id'])
        self.fixture.login('copyother', 'operator-password-123')
        catalog = self.client.get('/api/ai-copy/brands').json()['brands']
        self.assertIn(created['id'], [b['id'] for b in catalog])
        response = self.client.get('/api/ai-copy/history/' + record['generation_id'], headers=self.headers(created))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['title'], record['title'])
        self.assertEqual(self.profile(created)['sample_count'], 0)
        reopened = BrandCopyHistory(self.store.path)
        self.assertIn(created['id'], [b['id'] for b in reopened.brands(self.other['id'])])

    def test_duplicate_creation_returns_existing_brand_without_overwriting_profile(self):
        brand = self.new_brand('Example Brand')
        self.fixture.login('copyoperator', 'operator-password-123')
        duplicate = self.client.post('/api/ai-copy/brands', headers=self.headers(), json={'name': '  ＥＸＡＭＰＬＥ   ＢＲＡＮＤ  '})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(duplicate.json()['existing_brand']['id'], brand['id'])
        self.assertTrue(duplicate.json()['existing_brand']['enabled'])
        self.assertEqual(len(self.client.get('/api/ai-copy/brands').json()['brands']), 3)
        self.assertEqual(self.store.profile(brand['id'])['version'], 0)

    def test_legacy_member_bindings_do_not_limit_shared_brand_access(self):
        with closing(self.store.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS copy_brand_members(brand_id TEXT,user_id TEXT)')
            db.execute('INSERT INTO copy_brand_members VALUES(?,?)', (self.brand['id'], self.admin['id']))
        self.fixture.login('copyother', 'operator-password-123')
        self.assertEqual(self.profile()['brand_id'], self.brand['id'])
        self.assertEqual(self.profile(self.second)['brand_id'], self.second['id'])

    def test_disabled_duplicate_is_not_recreated_and_admin_can_restore(self):
        disabled = self.store.save_brand(self.admin['id'], self.brand['name'], brand_id=self.brand['id'], version=0, enabled=False)
        self.fixture.login('copyoperator', 'operator-password-123')
        duplicate = self.client.post('/api/ai-copy/brands', headers=self.headers(), json={'name': self.brand['name']})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertFalse(duplicate.json()['existing_brand']['enabled'])
        self.assertEqual(duplicate.json()['existing_brand']['id'], self.brand['id'])
        self.fixture.login('admin', 'admin-password-123')
        restored = self.client.patch('/api/ai-copy/brands/' + self.brand['id'], headers=self.headers(), json={
            'name': self.brand['name'], 'enabled': True, 'version': disabled['version']})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.fixture.login('copyoperator', 'operator-password-123')
        self.assertEqual(self.profile()['brand_id'], self.brand['id'])

    def test_public_creation_requires_login_and_cannot_assign_members_or_create_disabled_brand(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/ai-copy/brands').status_code, 401)
        self.assertEqual(self.client.post('/api/ai-copy/brands', json={'name': 'anonymous'}).status_code, 401)
        self.fixture.login('copyoperator', 'operator-password-123')
        for invalid in ({'name': '   '}, {'name': 'invalid', 'members': [self.admin['id']]}, {'name': 'invalid', 'enabled': False}):
            response = self.client.post('/api/ai-copy/brands', headers=self.headers(), json=invalid)
            self.assertEqual(response.status_code, 422, response.text)

    def test_html_entry_is_not_cached(self):
        from dataclasses import replace
        from webapp.api.main import create_app
        dist = self.fixture.data_paths.root.parent / 'frontend'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'index.html').write_text('<!doctype html><title>test</title>', encoding='utf-8')
        settings = replace(self.fixture.app.state.settings, frontend_dist_dir=dist)
        application = create_app(settings, self.fixture.registry)
        client = auth_tests._AsgiClient(application)
        response = client.get('/')
        self.assertEqual(response.status_code, 200, response.text)
        headers = dict(client.last_response_headers)
        self.assertIn(b'no-store', headers[b'cache-control'])


if __name__ == '__main__':
    unittest.main()
