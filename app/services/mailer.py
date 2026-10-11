"""只负责发邮件。不碰数据库，也不碰 Flask。

两种后端（环境变量 MAIL_BACKEND 可强制指定，否则自动选择）：
  - smtp：设置了 SMTP_HOST 就用它。任何支持 SMTP 的服务都行（Gmail 应用专用密码、Brevo、Resend、SendGrid、公司邮箱……），
          所以不绑定某一家服务商。
  - console：没配置 SMTP 时用。邮件不会真的发出去，而是打印在服务器日志里（链接也在里面），本机开发可以直接点链接测试。
  - off：完全关闭发信。
所有错误都翻译成 MailError（带给用户看的英文提示），真实原因写进日志。
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from . import demo_mode

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15
OUTBOX = []          # console 后端和测试用：最近发出的邮件（只在内存里，最多 50 封）
OUTBOX_LIMIT = 50


class MailError(Exception):
    """发信失败。user_message 可以直接显示给用户。"""

    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


def backend():
    if demo_mode.enabled():  # 作品集演示：完全不发邮件
        return "off"
    forced = os.getenv("MAIL_BACKEND", "").strip().lower()
    if forced in ("smtp", "console", "off"):
        return forced
    return "smtp" if os.getenv("SMTP_HOST", "").strip() else "console"


def enabled():
    return backend() != "off"


def real():
    """邮件会不会真的发到收件人手里。console 模式下是 False，页面上会如实告知。"""
    return backend() == "smtp"


def sender():
    """发件人。MAIL_FROM 可以写成 “Assignment Helper <noreply@example.com>” 或只写地址。"""
    raw = os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USERNAME", "").strip() or "noreply@localhost"
    name, address = parseaddr(raw)
    return formataddr((name or "Assignment Helper", address))


def _clean(value):
    """去掉换行，防止有人在主题或地址里塞进额外的邮件头（header injection）。"""
    return " ".join(str(value).split())


def build_message(to, subject, text, html=None):
    msg = EmailMessage()
    msg["From"] = sender()
    msg["To"] = _clean(to)
    msg["Subject"] = _clean(subject)[:200]
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _smtp_class():
    """单独成函数：测试时替换成假的 SMTP，就不会连真实的服务器。"""
    return smtplib.SMTP_SSL if os.getenv("SMTP_SECURITY", "starttls").strip().lower() == "ssl" else smtplib.SMTP


def send(to, subject, text, html=None):
    """发一封邮件。console 模式只记录；smtp 模式真的发送。失败抛出 MailError。"""
    if not enabled():
        raise MailError("Email is turned off on this server.")
    msg = build_message(to, subject, text, html)
    mode = backend()
    if mode == "console":
        OUTBOX.append(msg)
        del OUTBOX[:-OUTBOX_LIMIT]
        logger.warning("[email not actually sent: MAIL_BACKEND=console]\nTo: %s\nSubject: %s\n\n%s", msg["To"], msg["Subject"], text)
        return
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    security = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    user, password = os.getenv("SMTP_USERNAME", "").strip(), os.getenv("SMTP_PASSWORD", "")
    try:
        smtp_class = _smtp_class()
        kwargs = {"timeout": TIMEOUT_SECONDS}
        if smtp_class is smtplib.SMTP_SSL:
            kwargs["context"] = ssl.create_default_context()
        with smtp_class(host, port, **kwargs) as server:
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if user:
                server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        logger.warning("SMTP 登录失败：%s", e)
        raise MailError("The server could not log in to the email service. Please contact the administrator.") from e
    except smtplib.SMTPRecipientsRefused as e:
        logger.warning("收件人被拒绝：%s", e)
        raise MailError("The email address was refused by the email service.") from e
    except (smtplib.SMTPException, OSError) as e:
        logger.warning("发信失败：%s", e)
        raise MailError("The email could not be sent right now. Please try again later.") from e
    OUTBOX.append(msg)
    del OUTBOX[:-OUTBOX_LIMIT]
