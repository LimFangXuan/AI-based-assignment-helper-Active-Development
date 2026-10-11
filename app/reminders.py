"""每日摘要和截止日提醒。由定时任务调用（send_reminders.py，或带令牌的 POST /cron/reminders），建议每小时运行一次。

规则（每个用户按自己的时区计算）：
  - 每日摘要：本地时间到了用户设的钟点（默认 8 点）之后、22 点之前，当天只发一次；今天没有任务也没有截止日就不发。
    内容：今天要做的任务 + 已经逾期还没做的 + 今天截止的项目。
  - 截止日提醒：项目截止前 72 小时和 24 小时各提醒一次（已提交的项目不提醒）。改了截止时间就会重新提醒。
  - 渠道：用户分别选了邮件和 / 或推送。邮件必须是验证过的邮箱；推送必须至少有一台已订阅的设备。
  - 防重复：NotificationLog 里 (用户, 类型, 参考键) 唯一，同一条提醒不会发第二次。发送失败（比如邮件服务暂时不可用）不会记录，下次运行会再试。
  - 推送服务回复“设备已失效”(404/410) 时，自动删除那台设备的订阅。
建议只让一个定时任务在跑；同时跑两个有极小的概率重复发送。
"""
import logging
import zoneinfo
from datetime import datetime, timezone

from flask import current_app, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from . import emails, urls
from .constants import DEADLINE_REMINDER_HOURS, DIGEST_LAST_HOUR, DIGEST_MAX_TASKS
from .extensions import db
from .models import NotificationLog, Project, Task, User
from .services import mailer, push

logger = logging.getLogger(__name__)


def user_tz(user):
    try:
        return zoneinfo.ZoneInfo(user.timezone or "UTC")
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return zoneinfo.ZoneInfo("UTC")


def email_usable(user):
    return bool(mailer.enabled() and user.email and user.email_verified)


# ======================= 发送（提醒和 Settings 里的“发测试”共用） =======================
def deliver_email(user, message):
    """message = (主题, 纯文本, HTML)。返回 (是否成功, 给用户看的说明)。"""
    if not email_usable(user):
        return False, "Verify your email address first."
    try:
        mailer.send(user.email, *message)
    except mailer.MailError as e:
        return False, e.user_message
    return True, "Email sent."


def deliver_push(user, title, body, path, tag):
    """发给这个用户所有已订阅的设备；失效的订阅顺便删掉。返回 (至少一台成功, 说明)。"""
    subs = list(user.push_subscriptions)
    if not subs:
        return False, "No device is subscribed yet."
    sent = 0
    for sub in subs:
        try:
            push.send(sub.as_info(), title, body, path, tag)
            sent += 1
        except push.PushGone:
            db.session.delete(sub)
        except push.PushError:
            logger.warning("给用户 %s 的一台设备推送失败", user.id)
    db.session.commit()
    if sent:
        return True, f"Notification sent to {sent} device{'s' if sent != 1 else ''}."
    return False, "The notification could not be delivered to any device."


# ======================= 内容 =======================
def minutes_label(minutes):
    if not minutes:
        return ""
    hours, rest = divmod(minutes, 60)
    return f"{minutes} min" if not hours else (f"{hours} h {rest} min" if rest else f"{hours} h")


def digest_items(user, tz, local_now):
    today = local_now.date()
    tasks = (Task.query.join(Project)
             .filter(Project.user_id == user.id, Project.status != "submitted", Task.done.is_(False),
                     Task.due_date.isnot(None), Task.due_date <= today)
             .order_by(Task.due_date.asc(), Task.position.asc(), Task.id.asc()).all())
    shown = [{"title": t.title, "project": t.project.name, "minutes": minutes_label(t.minutes),
              "when": "overdue" if t.due_date < today else ""} for t in tasks[:DIGEST_MAX_TASKS]]
    due_today = []
    for p in Project.query.filter(Project.user_id == user.id, Project.status != "submitted").all():
        deadline = p.deadline.replace(tzinfo=tz)
        if deadline.date() == today and deadline >= local_now:
            due_today.append({"project": p.name, "time": deadline.strftime("%H:%M")})
    return shown, max(0, len(tasks) - DIGEST_MAX_TASKS), due_today


def human_left(hours):
    if hours < 1:
        return "less than an hour"
    if hours < 48:
        return f"about {round(hours)} hour{'s' if round(hours) != 1 else ''}"
    return f"about {round(hours / 24)} days"


# ======================= 主流程 =======================
def already_sent(user, kind, ref_key):
    return NotificationLog.query.filter_by(user_id=user.id, kind=kind, ref_key=ref_key).first() is not None


def record(user, kind, ref_key, channels):
    db.session.add(NotificationLog(user_id=user.id, kind=kind, ref_key=ref_key, channels=",".join(channels)))
    try:
        db.session.commit()
    except IntegrityError:  # 另一个同时运行的任务刚发过：不算错
        db.session.rollback()


def send_via_channels(user, want_email, want_push, make_email, push_args, stats):
    """按用户选的渠道发送。返回成功的渠道列表（空列表表示一个都没成功，调用方不记录、下次再试）。"""
    done = []
    if want_email and email_usable(user):
        ok, _ = deliver_email(user, make_email())
        if ok:
            done.append("email")
            stats["emails"] += 1
        else:
            stats["errors"] += 1
    if want_push and user.push_subscriptions:
        ok, _ = deliver_push(user, *push_args)
        if ok:
            done.append("push")
            stats["pushes"] += 1
        else:
            stats["errors"] += 1
    return done


def process_digest(user, tz, now, stats):
    local_now = now.astimezone(tz)
    if not user.digest_hour <= local_now.hour < DIGEST_LAST_HOUR:
        return
    ref = local_now.date().isoformat()
    want_email = user.notify_email_digest and email_usable(user)
    want_push = user.notify_push_digest and bool(user.push_subscriptions)
    if not (want_email or want_push) or already_sent(user, "digest", ref):
        return
    tasks, extra, due_today = digest_items(user, tz, local_now)
    if not tasks and not due_today:
        record(user, "digest", ref, [])  # 今天没什么要提醒的：记一笔，不再重复计算
        stats["skipped"] += 1
        return
    total = len(tasks) + extra
    title = f"{total} task{'s' if total != 1 else ''} for today" if tasks else "A deadline is today"
    body = "; ".join([t["title"] for t in tasks[:2]] + [f"{d['project']} due {d['time']}" for d in due_today[:1]])
    if total > 2:
        body += f" and {total - 2} more"
    today_url = urls.link("overview.today")
    settings_url = urls.link("settings.index")
    done = send_via_channels(user, want_email, want_push,
                             lambda: emails.digest(user, tasks, due_today, today_url, settings_url, extra),
                             (title, body, url_for("overview.today"), "digest"), stats)
    if done:
        record(user, "digest", ref, done)


def process_deadlines(user, tz, now, stats):
    want_email = user.notify_email_deadlines and email_usable(user)
    want_push = user.notify_push_deadlines and bool(user.push_subscriptions)
    if not (want_email or want_push):
        return
    due = []
    for p in Project.query.filter(Project.user_id == user.id, Project.status != "submitted").order_by(Project.deadline).all():
        deadline = p.deadline.replace(tzinfo=tz)
        hours = (deadline - now).total_seconds() / 3600
        if hours <= 0:
            continue
        kind = next((k for limit, k in sorted(DEADLINE_REMINDER_HOURS) if hours <= limit), None)
        ref = f"{p.id}|{p.deadline.isoformat()}"
        if kind and not already_sent(user, kind, ref):
            when = f"due in {human_left(hours)} ({deadline.strftime('%a %d %b, %H:%M')})"
            due.append({"project": p.name, "when": when, "kind": kind, "ref": ref})
    if not due:
        return
    title = f"Deadline soon: {due[0]['project']}" if len(due) == 1 else f"{len(due)} deadlines coming up"
    body = "; ".join(f"{d['project']} {d['when'].split(' (')[0]}" for d in due[:3])
    plan_url, settings_url = urls.link("overview.today"), urls.link("settings.index")
    done = send_via_channels(user, want_email, want_push,
                             lambda: emails.deadline_reminder(user, due, plan_url, settings_url),
                             (title, body, url_for("overview.upcoming"), "deadline"), stats)
    if done:
        for d in due:
            record(user, d["kind"], d["ref"], done)


def run(now=None):
    """给所有开了通知的用户处理摘要和截止日提醒。返回统计字典。now 默认是当前的 UTC 时间（测试里可以指定）。"""
    now = now or datetime.now(timezone.utc)
    stats = {"users": 0, "emails": 0, "pushes": 0, "skipped": 0, "errors": 0}
    users = User.query.filter(or_(User.notify_email_digest.is_(True), User.notify_email_deadlines.is_(True),
                                  User.notify_push_digest.is_(True), User.notify_push_deadlines.is_(True))).all()
    with current_app.test_request_context(base_url=urls.base_url()):  # 生成链接需要一个请求上下文
        for user in users:
            stats["users"] += 1
            tz = user_tz(user)
            try:
                process_digest(user, tz, now, stats)
                process_deadlines(user, tz, now, stats)
            except Exception:  # 一个用户出问题不能影响其他人
                db.session.rollback()
                stats["errors"] += 1
                logger.exception("处理用户 %s 的提醒时出错", user.id)
    return stats
