import json
from contextlib import nullcontext
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import MagicMock

from webapp.category_insights import build_scopes, cached_category_insights


def dashboard():
    return {'brand': {'id': 1}, 'selected_period': '2026-08', 'tags': {'video': [
        {'id': '种草短视频 · 桌面', 'category': '种草短视频', 'subcategory': '桌面', 'contentCount': 10, 'viralCount': 1, 'exposure': 100, 'clicks': 8, 'product_click_users': 4, 'revenue': 20, 'samples': []},
        {'id': '种草短视频 · 车载', 'category': '种草短视频', 'subcategory': '车载', 'contentCount': 2, 'viralCount': 0, 'exposure': 0, 'clicks': 0, 'product_click_users': 0, 'revenue': 0, 'samples': []},
    ], 'image': []}}


def provider_for(data):
    provider = MagicMock()
    provider.ready = True
    provider.model = 'test'
    provider.session.side_effect = lambda: nullcontext()
    ids = [f'c{index}' for index, row in enumerate([row for info in build_scopes(data).values() for row in info['rows']])]
    provider.chat.return_value = {'content': json.dumps({'items': [{'id': key, 'strength': '曝光贡献领先', 'weakness': '仍需验证点击效率', 'suggestion': '测试商品点击引导并对比点击率'} for key in ids]})}
    return provider


def test_scopes_compare_siblings_and_handle_zero_exposure():
    scopes = build_scopes(dashboard())
    assert scopes['video:all']['rows'][0]['contentCount'] == 12
    assert scopes['video:种草短视频']['baselineClickRate'] == 4
    assert scopes['video:种草短视频']['rows'][1]['clickRate'] is None


def test_persistent_cache_reuses_and_invalidates_on_new_data():
    data = dashboard()
    provider = provider_for(data)
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'cache.sqlite3'
        first = cached_category_insights(data, provider, path)
        assert first['status'] == 'ready'
        assert first['scopes']['video:all'][0]['suggestion'] == '测试商品点击引导并对比点击率'
        assert cached_category_insights(deepcopy(data), provider, path) == first
        assert provider.chat.call_count == 1
        data['tags']['video'][0]['samples'].append({'content_id': 'new'})
        cached_category_insights(data, provider, path)
        assert provider.chat.call_count == 2
        data['brand']['id'] = 2
        cached_category_insights(data, provider, path)
        assert provider.chat.call_count == 3


def test_invalid_ai_response_is_not_shown_and_has_retry_cooldown():
    data = dashboard()
    provider = provider_for(data)
    provider.chat.return_value = {'content': '{"items":[]}'}
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'cache.sqlite3'
        assert cached_category_insights(data, provider, path)['status'] == 'unavailable'
        cached_category_insights(data, provider, path)
        assert provider.chat.call_count == 1
