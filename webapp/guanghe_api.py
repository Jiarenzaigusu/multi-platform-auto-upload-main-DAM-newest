"""Read authorized Guanghe content through the free TOP detail API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://eco.taobao.com/router/rest"
METHOD = "taobao.guangguang.content.trial.queryproducercontentdetail"
RESPONSE_KEY = "guangguang_content_trial_queryproducercontentdetail_response"


class GuangheApiError(RuntimeError):
    pass


def content_detail(content_id: str) -> dict:
    if not content_id.isascii() or not content_id.isdigit() or len(content_id) > 20:
        raise ValueError("作品号必须是 1 至 20 位数字")

    app_key = os.getenv("MPAU_TOP_APP_KEY", "").strip()
    secret = os.getenv("MPAU_TOP_APP_SECRET", "").strip()
    session = os.getenv("MPAU_TOP_SESSION", "").strip()
    if not all((app_key, secret, session)):
        return {"configured": False, "missing_settings": [name for name, value in (
            ("MPAU_TOP_APP_KEY", app_key),
            ("MPAU_TOP_APP_SECRET", secret),
            ("MPAU_TOP_SESSION", session),
        ) if not value]}

    params = {
        "method": METHOD,
        "app_key": app_key,
        "session": session,
        "timestamp": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "sign_method": "hmac",
        "trial_base_request": json.dumps({"content_id": int(content_id), "page_no": 1, "page_size": 10}, separators=(",", ":")),
    }
    signing_text = "".join(key + params[key] for key in sorted(params))
    params["sign"] = hmac.new(secret.encode(), signing_text.encode(), hashlib.md5).hexdigest().upper()
    request = Request(API_URL, data=urlencode(params).encode(), headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise GuangheApiError("光合接口连接失败") from exc

    if "error_response" in payload:
        error = payload["error_response"]
        raise GuangheApiError(str(error.get("sub_msg") or error.get("msg") or "光合接口请求失败"))
    result = payload.get(RESPONSE_KEY, {}).get("result", {})
    if not result.get("success") or not isinstance(result.get("model"), dict):
        raise GuangheApiError(str(result.get("msg_info") or "未查到作品详情"))
    model = result["model"]
    if str(model.get("content_id", "")) != content_id:
        raise GuangheApiError("光合返回的作品号与请求不一致")
    return {
        "configured": True,
        "content_id": content_id,
        "content_type": model.get("content_type"),
        "title": model.get("title") or "",
        "summary": model.get("summary") or "",
        "cover_url": model.get("cover_url") or "",
        "pic_urls": model.get("pic_url") or [],
        "video_url": model.get("video_url") or "",
        "favor_count": model.get("favor_count"),
        "collect_count": model.get("collect_count"),
        "comment_count": model.get("comment_count"),
        "item_url": model.get("item_url") or "",
    }
