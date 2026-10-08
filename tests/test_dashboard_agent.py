from contextlib import nullcontext
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from webapp.dashboard_agent import ChatRequest, ConversationStore, DashboardTools, _concise_answer, _name_works, answer_question


class DashboardAgentTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = {
            'brand': {'id': 7, 'name': '星巴克'}, 'selected_period': '2026-08',
            'periods': [{'key': '2026-08'}, {'key': '2026-07'}],
            'tags': {'image': [{'id': '图文', 'category': '图文'}], 'video': [{'id': '往期视频', 'category': '往期视频'}]},
        }

    def test_queries_are_brand_period_and_tag_scoped(self):
        database = MagicMock()
        database.execute.return_value = [(2, 100, 200, 10, 30, 300)]
        tools = DashboardTools(database, self.dashboard, 'video', '往期视频')
        result = tools.get_metrics()
        self.assertEqual(result['scope'], '往期视频')
        query, params = database.execute.call_args.args
        self.assertIn('`汇总分类` = %s', query)
        self.assertEqual(params, (7, 2026, '8月', '图文', '往期视频'))
        with self.assertRaises(ValueError):
            DashboardTools(database, self.dashboard, 'video', '其他品牌标签')
        database.execute.return_value = []
        with self.assertRaises(ValueError):
            tools.get_content_history('unknown')
        self.assertEqual(database.execute.call_count, 2)

    def test_store_keeps_scope_and_recent_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(Path(tmp) / 'chat.sqlite3')
            cid, messages = store.open(7, '2026-08', 'image', 'all')
            self.assertEqual(messages, [])
            store.append(cid, '哪类内容好？', '图文点击更多。', [{'tool': 'get_metrics', 'result': {'count': 2}}])
            cid2, messages = store.open(7, '2026-08', 'image', 'all')
            self.assertEqual(cid, cid2)
            self.assertEqual(messages[-1]['evidence'][0]['result']['count'], 2)
            with self.assertRaises(ValueError):
                store.open(8, '2026-08', 'image', 'all', cid)
            with self.assertRaises(ValueError):
                store.open(7, '2026-07', 'image', 'all', cid)

    def test_model_tool_call_uses_server_result(self):
        database = MagicMock()
        database.execute.return_value = [(2, 100, 200, 10, 30, 300)]
        tools = DashboardTools(database, self.dashboard, 'image', 'all')
        provider = MagicMock()
        provider.session.return_value = nullcontext()
        provider.chat.side_effect = [
            {'content': None, 'tool_calls': [{'id': 'call1', 'function': {'name': 'get_metrics', 'arguments': '{}'}}]},
            {'content': '本期图文有 2 条。'},
        ]
        answer, evidence = answer_question(provider, tools, [], '本期图文有几条？')
        self.assertEqual(answer, '本期图文有 2 条。')
        self.assertEqual(evidence[0]['result']['content_count'], 2)
        self.assertEqual(provider.chat.call_count, 2)
        self.assertEqual(provider.chat.call_args.args[0][-1]['role'], 'tool')

    def test_long_table_answer_is_summarized(self):
        database = MagicMock()
        database.execute.return_value = [(2, 100, 200, 10, 30, 300)]
        tools = DashboardTools(database, self.dashboard, 'image', 'all')
        provider = MagicMock()
        provider.session.return_value = nullcontext()
        provider.chat.side_effect = [
            {'content': None, 'tool_calls': [{'id': 'call1', 'function': {'name': 'get_metrics', 'arguments': '{}'}}]},
            {'content': '| 指标 | 数值 |\n|---|---|\n| 内容数 | 2 |'},
            {'content': '本期图文有 2 条内容；完整数据可展开查看。'},
        ]
        answer, evidence = answer_question(provider, tools, [], '分析本期内容')
        self.assertEqual(answer, '本期图文有 2 条内容；完整数据可展开查看。')
        self.assertEqual(len(evidence), 1)
        self.assertEqual(provider.chat.call_count, 3)

    def test_formatted_answer_keeps_layout(self):
        provider = MagicMock()
        answer = '**结论：继续做《杯具合集》。**\n\n依据：\n- 曝光 1,000 人。\n- 点击 100 人。\n\n口径说明：人数未跨内容去重。'
        self.assertEqual(_concise_answer(provider, answer), answer)
        provider.chat.assert_not_called()

    def test_ranked_work_ids_use_titles_when_available(self):
        answer = _name_works('推荐 `460235214175`（成交 2,978）和 472447801879（点击 364）。', [
            {'tool': 'rank_contents', 'result': [
                {'content_id': '460235214175', 'title': '杯具合集'},
                {'content_id': '472447801879', 'title': ''},
            ]},
        ])
        self.assertEqual(answer, '推荐 《杯具合集》（成交 2,978）和 472447801879（点击 364）。')

    def test_quoted_references_resolve_normalized_titles_in_scope(self):
        database = MagicMock()
        database.execute.return_value = [
            ('123', '甜夏赴约｜夏日甜品派对站🍮'),
            ('456', '新品！豹纹咖调🐆'),
            ('789', '豹纹咖调礼盒'),
        ]
        tools = DashboardTools(database, self.dashboard, 'video', 'all')
        references = tools.content_references(['推荐“甜夏赴约|夏日甜品派对站”和“豹纹咖调”。'])
        self.assertEqual(references, [{'content_id': '123', 'title': '甜夏赴约｜夏日甜品派对站🍮', 'label': '甜夏赴约|夏日甜品派对站'}])
        query, params = database.execute.call_args.args
        self.assertIn('brand_id = %s', query)
        self.assertEqual(params, (7, 2026, '8月', '图文'))
        database.reset_mock()
        self.assertEqual(tools.content_references(['本期成交增长。']), [])
        database.execute.assert_not_called()

    def test_rejects_invalid_request_scope(self):
        with self.assertRaises(ValueError):
            ChatRequest(question='hi', period='2026-99', content_type='other')


if __name__ == '__main__':
    unittest.main()
