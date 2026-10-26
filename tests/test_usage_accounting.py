from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from webapp.llm_adapter.catalog import AdapterKind
from webapp.llm_adapter.provider import OpenAICompatibleProvider
from webapp.llm_adapter.registry import LLMAdapterRegistry
from webapp.usage import UsageStore, read_rows


class UsageAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UsageStore(Path(self.temp.name) / 'usage.sqlite3')
        self.registry = LLMAdapterRegistry(usage_recorder=lambda **event: self.store.record(user_id='a'*32, **event))
        self.registry.activate(AdapterKind.DEEPSEEK, 'not-a-real-key')

    def response(self, usage):
        return BytesIO(json.dumps({'choices': [{'message': {'content': 'reply'}}], 'usage': usage}).encode())

    def test_records_each_retry_and_response_without_content_or_credentials(self):
        opener = Mock()
        opener.open.side_effect = [URLError('timeout'), self.response({
            'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20,
            'prompt_tokens_details': {'cached_tokens': 5}})]
        with patch('webapp.llm_adapter.provider.build_opener', return_value=opener), patch('webapp.llm_adapter.provider.time.sleep'):
            result = OpenAICompatibleProvider(self.registry, feature='ai_copy').chat([{'role': 'user', 'content': 'private prompt'}])
        self.assertEqual(result, {'content': 'reply'})
        rows = read_rows(self.store.path, 'SELECT * FROM llm_usage ORDER BY created_at')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['status'], 'transport_error')
        self.assertIsNone(rows[0]['total_tokens'])
        self.assertEqual(rows[1]['total_tokens'], 20)
        self.assertEqual(rows[1]['cached_input_tokens'], 5)
        self.assertEqual(rows[1]['feature'], 'ai_copy')
        self.assertEqual(rows[1]['user_id'], 'a'*32)
        self.assertNotIn('private prompt', json.dumps(rows))
        self.assertNotIn('not-a-real-key', json.dumps(rows))

    def test_probe_is_attributed_to_probe_and_missing_usage_is_null(self):
        opener = Mock()
        opener.open.return_value = self.response(None)
        with patch('webapp.llm_adapter.provider.build_opener', return_value=opener):
            OpenAICompatibleProvider(self.registry).probe(self.registry.snapshot())
        row = read_rows(self.store.path, 'SELECT * FROM llm_usage')[0]
        self.assertEqual(row['feature'], 'adapter_probe')
        self.assertIsNone(row['total_tokens'])

    def test_invalid_usage_is_unknown_and_valid_components_can_be_summed(self):
        for usage in ({'prompt_tokens': True, 'completion_tokens': -1, 'total_tokens': '20'},
                      {'prompt_tokens': 4, 'completion_tokens': 6}, {'total_tokens': 15}):
            self.store.record(user_id='b'*32, provider='qwen', model='test', feature='smart_sheet', usage=usage, status='response')
        rows = read_rows(self.store.path, 'SELECT * FROM llm_usage ORDER BY created_at')
        self.assertIsNone(rows[0]['input_tokens'])
        self.assertIsNone(rows[0]['output_tokens'])
        self.assertIsNone(rows[0]['total_tokens'])
        self.assertEqual(rows[1]['total_tokens'], 10)
        self.assertEqual(rows[2]['total_tokens'], 15)
        self.assertIsNone(rows[2]['input_tokens'])

    def test_accounting_failure_does_not_repeat_or_fail_model_request(self):
        self.registry.usage_recorder = Mock(side_effect=sqlite3.OperationalError('private details'))
        opener = Mock()
        opener.open.return_value = self.response({'total_tokens': 10})
        with patch('webapp.llm_adapter.provider.build_opener', return_value=opener), self.assertLogs('webapp.llm_adapter.provider') as logs:
            self.assertEqual(OpenAICompatibleProvider(self.registry).chat([])['content'], 'reply')
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn('private details', str(logs.output))
