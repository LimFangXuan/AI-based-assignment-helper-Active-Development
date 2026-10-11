"""只负责 Web Push（浏览器推送通知）。不碰数据库，也不碰 Flask 的 session。

工作方式：
  - 服务器有一对 VAPID 密钥（公钥给浏览器订阅用，私钥用来给每条推送签名，证明消息来自我们）。
    密钥来自环境变量 VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY；没设置时第一次用到会自动生成并存在 instance/vapid.json。
    部署时一定要用环境变量固定下来：换密钥后，所有已订阅的设备都要重新订阅。
  - 浏览器订阅后给我们一个 endpoint 和两个密钥；send() 用它们加密并发给推送服务（Google / Mozilla / Apple）。
  - 推送服务回 404 / 410 表示这台设备已经取消订阅，抛出 PushGone，调用方负责把它从数据库删掉。
"""
import base64
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

TTL_SECONDS = 12 * 3600  # 设备离线时，推送服务最多帮我们保留这条消息多久
TIMEOUT_SECONDS = 10


class PushError(Exception):
    """推送失败（临时性的）。"""


class PushGone(Exception):
    """这个订阅已经失效（用户取消了订阅或清除了浏览器数据），应该删除。"""


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate():
    vapid = Vapid()
    vapid.generate_keys()
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(private), _b64(public)


def _key_file():
    return Path(os.getenv("VAPID_KEY_FILE", "")) if os.getenv("VAPID_KEY_FILE") else Path("instance") / "vapid.json"


def keys():
    """返回 (私钥, 公钥)，都是 base64url 字符串。优先环境变量，其次 instance/vapid.json，都没有就生成并保存。"""
    private, public = os.getenv("VAPID_PRIVATE_KEY", "").strip(), os.getenv("VAPID_PUBLIC_KEY", "").strip()
    if private and public:
        return private, public
    path = _key_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("private") and data.get("public"):
            return data["private"], data["public"]
    except (OSError, ValueError):
        pass
    private, public = _generate()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"private": private, "public": public}), encoding="utf-8")
        logger.warning("已生成新的 VAPID 密钥并保存到 %s。部署时请改用环境变量 VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY。", path)
    except OSError:
        logger.warning("无法保存 VAPID 密钥文件；本次运行内有效，重启后需要重新订阅。")
    return private, public


def public_key():
    return keys()[1]


def subject():
    """VAPID 的联系方式（推送服务出问题时联系你）。Apple 要求是有效的 mailto: 或 https: 地址。"""
    explicit = os.getenv("VAPID_SUBJECT", "").strip()
    if explicit:
        return explicit
    sender = os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USERNAME", "").strip()
    address = sender.split("<")[-1].strip(" >") if sender else ""
    return f"mailto:{address}" if "@" in address else "mailto:admin@example.com"


def _webpush(**kwargs):
    """单独成函数：测试时替换成假的，就不会连真实的推送服务。"""
    return webpush(**kwargs)


def send(subscription, title, body, url="/", tag=None):
    """给一台设备发一条通知。subscription 是 {"endpoint", "keys": {"p256dh", "auth"}}。"""
    payload = json.dumps({"title": title[:120], "body": body[:300], "url": url, "tag": tag or "assignment-helper"})
    try:
        _webpush(subscription_info=subscription, data=payload, vapid_private_key=keys()[0],
                 vapid_claims={"sub": subject()}, ttl=TTL_SECONDS, timeout=TIMEOUT_SECONDS)
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone() from e
        logger.warning("推送失败（%s）：%s", status, e)
        raise PushError("The push service did not accept the notification.") from e
    except Exception as e:  # 网络问题、订阅数据格式不对等
        logger.warning("推送出错：%s", e)
        raise PushError("The notification could not be sent.") from e
