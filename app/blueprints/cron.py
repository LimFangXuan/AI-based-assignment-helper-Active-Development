"""给没有 cron 的托管平台用：定时用 POST 访问这个地址来触发提醒。

必须设置环境变量 REMINDER_TOKEN（一串足够长的随机字符），请求头带上 Authorization: Bearer <令牌>。
没设置令牌、令牌不对时一律返回 404（不暴露这个入口存在），所以默认是关闭的。
"""
import hmac
import os

from flask import Blueprint, abort, jsonify, request

from .. import reminders as engine

bp = Blueprint("cron", __name__)


@bp.route("/cron/reminders", methods=["POST"])
def reminders():
    expected = os.getenv("REMINDER_TOKEN", "").strip()
    header = request.headers.get("Authorization", "")
    sent = header[7:].strip() if header.startswith("Bearer ") else ""
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        abort(404)
    return jsonify(engine.run())
