"""账号相关的邮件：验证邮箱、重置密码、安全提醒。内容在 emails.py，发送在 services/mailer.py。"""
import logging

from . import emails, tokens, urls
from .services import mailer

logger = logging.getLogger(__name__)


def send_verification(user):
    """给用户当前的邮箱发验证链接。返回 (是否成功, 给用户看的说明)。"""
    if not user.email:
        return False, "Add an email address first."
    url = urls.link("auth.verify_email", token=tokens.make_verify_token(user))
    try:
        mailer.send(user.email, *emails.verify_email(user, url))
    except mailer.MailError as e:
        return False, e.user_message
    if mailer.real():
        return True, f"We sent a confirmation link to {user.email}."
    return True, "Email isn't configured on this server, so the confirmation link was printed in the server log instead."


def send_reset(user):
    url = urls.link("auth.reset_password", token=tokens.make_reset_token(user))
    try:
        mailer.send(user.email, *emails.reset_password(user, url))
    except mailer.MailError:
        logger.warning("重置密码邮件没有发出去（用户 %s）", user.id)


def send_notice(user, message, address=None):
    """安全提醒（改密码、改邮箱）。只发给验证过的邮箱；失败不影响主流程。"""
    to = address or (user.email if user.email_verified else None)
    if not to or not mailer.enabled():
        return
    try:
        mailer.send(to, *message)
    except mailer.MailError:
        logger.warning("安全提醒邮件没有发出去（用户 %s）", user.id)
