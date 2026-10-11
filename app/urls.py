"""生成发在邮件和推送里的完整链接。

请求过程中用当前网站的地址；在定时任务（没有请求）里用 APP_BASE_URL。部署在代理后面、自动得到的地址不对时，
也设置 APP_BASE_URL（例如 https://app.example.com）。
"""
import os

from flask import has_request_context, request, url_for

DEFAULT_BASE = "http://127.0.0.1:5000"


def base_url():
    explicit = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return request.host_url.rstrip("/") if has_request_context() else DEFAULT_BASE


def link(endpoint, **values):
    """返回完整链接，例如 http://127.0.0.1:5000/reset-password/<token>。需要 app 上下文（定时任务里用 test_request_context）。"""
    return base_url() + url_for(endpoint, _external=False, **values)
