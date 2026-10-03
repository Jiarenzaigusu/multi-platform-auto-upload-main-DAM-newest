import json
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock

from webapp.content_analysis import DIMENSIONS, build_evidence, generate_analysis


class ContentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = {
            'brand': {'name': '星巴克'},
            'summary': {'current': {'label': '2026年8月', 'content_count': 1, 'content_viewers': 100, 'impression_users': 200, 'product_click_users': 10, 'revenue': 100, 'impressions': 400, 'interactions': 20, 'product_clicks': 15}, 'previous': None},
            'tags': {'video': [{'id': '往期视频', 'label': '往期视频', 'contentCount': 1, 'exposure': 200, 'product_click_users': 10, 'revenue': 100, 'samples': [{'content_id': '123', 'title': '甜品杯', 'meta': '发布于 2026-07-30', 'exposure': 200, 'product_click_users': 10, 'revenue': 100}]}]},
        }
        self.provider = MagicMock(model='test-model', provider_label='test-provider')
        self.provider.session.return_value = nullcontext()
        self.response = {'summary': '星巴克杯具数据分析，原因仍需测试。', 'insights': [
            {'dimension': DIMENSIONS[0], 'title': '作品表现', 'kind': '数据观察', 'text': '甜品杯贡献本期成交。', 'evidence_ids': ['content:123']},
            {'dimension': DIMENSIONS[1], 'title': '待验证方向', 'kind': '待验证假设', 'text': '送礼表达可能影响点击。', 'evidence_ids': ['click_ratio', 'retention_gap']},
            {'dimension': DIMENSIONS[2], 'title': '测试安排', 'kind': '执行建议', 'text': '保持价格一致测试两版封面。', 'evidence_ids': ['period', 'interaction_gap']},
            {'dimension': DIMENSIONS[3], 'title': '搜索缺失', 'kind': '执行建议', 'text': '补采搜索数据。', 'evidence_ids': ['search_gap', 'content:123']},
            {'dimension': DIMENSIONS[4], 'title': '商业效率', 'kind': '数据观察', 'text': '仅可评估点击与种草成交。', 'evidence_ids': ['conversion_gap']},
        ]}

    def test_grounded_response_and_server_calculated_evidence(self):
        self.provider.chat.return_value = {'content': json.dumps(self.response)}
        result = generate_analysis(self.dashboard, self.provider)
        self.assertEqual(result['model'], 'test-model')
        self.assertIn('100.00%', result['cards'][0]['evidence'][0])
        self.assertIn('5.00%', build_evidence(self.dashboard)['click_ratio'])
        self.assertEqual(result['cards'][1]['tag'], '待验证假设')

    def test_rejects_invented_and_missing_content_references(self):
        for key in ['content:other-brand', 'period']:
            with self.subTest(key=key):
                self.response['insights'][0]['evidence_ids'] = [key]
                self.response['insights'][3]['evidence_ids'] = ['search_gap', 'period']
                self.provider.chat.return_value = {'content': json.dumps(self.response)}
                with self.assertRaises(ValueError):
                    generate_analysis(self.dashboard, self.provider)

    def test_retries_invalid_model_output_once(self):
        self.provider.chat.side_effect = [
            {'content': 'invalid JSON'},
            {'content': json.dumps(self.response)},
        ]
        result = generate_analysis(self.dashboard, self.provider)
        self.assertEqual(len(result['cards']), 5)
        self.assertEqual(self.provider.chat.call_count, 2)

    def test_five_dimensions_are_required_in_order(self):
        for dimensions in ([DIMENSIONS[0]] * 5, list(reversed(DIMENSIONS))):
            with self.subTest(dimensions=dimensions):
                response = json.loads(json.dumps(self.response))
                for insight, dimension in zip(response['insights'], dimensions):
                    insight['dimension'] = dimension
                self.provider.chat.return_value = {'content': json.dumps(response)}
                with self.assertRaises(ValueError):
                    generate_analysis(self.dashboard, self.provider)

    def test_gap_only_analysis_is_rejected(self):
        self.response['insights'][3]['evidence_ids'] = ['search_gap']
        self.provider.chat.return_value = {'content': json.dumps(self.response)}
        with self.assertRaises(ValueError):
            generate_analysis(self.dashboard, self.provider)

    def test_custom_analysis_has_content_and_category_efficiency(self):
        evidence = build_evidence(self.dashboard)
        self.assertIn('5.00%', evidence['content_efficiency:123'])
        self.assertIn('5.00%', evidence['category_efficiency:往期视频'])

    def test_efficiency_evidence_preserves_metric_definitions(self):
        evidence = build_evidence(self.dashboard)
        self.assertIn('250.00', evidence['exposure_revenue'])
        self.assertIn('3.75%', evidence['pv_click_ratio'])
        self.assertIn('50.00', evidence['interaction_density'])
        self.assertIn('不是千次播放', evidence['exposure_revenue'])
        self.dashboard['summary']['current']['impressions'] = 0
        evidence = build_evidence(self.dashboard)
        self.assertNotIn('exposure_revenue', evidence)
        self.assertNotIn('pv_click_ratio', evidence)
        self.assertNotIn('interaction_density', evidence)

    def test_invalid_output_and_zero_denominators(self):
        self.provider.chat.return_value = {'content': 'invalid JSON'}
        with self.assertRaises(ValueError):
            generate_analysis(self.dashboard, self.provider)
        self.dashboard['summary']['current']['impression_users'] = 0
        self.dashboard['summary']['current']['revenue'] = 0
        evidence = build_evidence(self.dashboard)
        self.assertNotIn('click_ratio', evidence)
        self.assertNotIn('占本周期', evidence['content:123'])
