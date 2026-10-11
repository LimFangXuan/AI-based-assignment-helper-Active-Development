"""所有邮件的内容。每个函数返回 (主题, 纯文本, HTML)。

HTML 只用最简单的内联样式（邮件客户端对 CSS 支持很差），所有动态内容都经过转义。
邮件里不放用户的作业描述，只放项目名称和任务标题。
"""
from html import escape

APP = "Assignment Helper"


def _wrap(heading, paragraphs, button=None, footer=""):
    body = "".join(f'<p style="margin:0 0 14px;line-height:1.55;">{p}</p>' for p in paragraphs)
    cta = (f'<p style="margin:22px 0;"><a href="{escape(button[1])}" style="background:#2b2b31;color:#ffffff;padding:11px 20px;'
           f'border-radius:10px;text-decoration:none;font-weight:600;display:inline-block;">{escape(button[0])}</a></p>') if button else ""
    foot = f'<p style="margin:24px 0 0;color:#6c6c76;font-size:13px;line-height:1.5;">{footer}</p>' if footer else ""
    return (f'<div style="background:#f4f4f6;padding:24px 12px;"><div style="max-width:520px;margin:0 auto;background:#ffffff;'
            f'border-radius:16px;padding:28px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1c1c21;font-size:15px;">'
            f'<h1 style="margin:0 0 16px;font-size:20px;">{escape(heading)}</h1>{body}{cta}{foot}</div></div>')


def verify_email(user, url):
    text = (f"Hi {user.username},\n\nConfirm that {user.email} is your email address by opening this link "
            f"(valid for 3 days):\n\n{url}\n\nOnce confirmed you can reset your password by email and turn on email reminders.\n"
            f"If you did not add this address, you can ignore this message.\n\n{APP}")
    html = _wrap("Confirm your email address",
                 [f"Hi {escape(user.username)}, confirm that <strong>{escape(user.email)}</strong> is your email address."],
                 ("Confirm email", url), "The link is valid for 3 days. If you did not add this address, ignore this message.")
    return f"Confirm your email for {APP}", text, html


def reset_password(user, url):
    text = (f"Hi {user.username},\n\nSomeone (hopefully you) asked to reset the password for your {APP} account.\n"
            f"Choose a new password here (valid for 1 hour, works once):\n\n{url}\n\n"
            f"If this wasn't you, ignore this message: your password has not changed.\n\n{APP}")
    html = _wrap("Reset your password", [f"Hi {escape(user.username)}, someone (hopefully you) asked to reset your password."],
                 ("Choose a new password", url),
                 "The link is valid for 1 hour and works once. If this wasn't you, ignore this message: your password has not changed.")
    return f"Reset your {APP} password", text, html


def password_changed(user, how="changed"):
    text = (f"Hi {user.username},\n\nThe password for your {APP} account was just {how}.\n"
            f"If this was you, no action is needed. If it wasn't, reset your password right away.\n\n{APP}")
    html = _wrap(f"Your password was {how}", [f"Hi {escape(user.username)}, the password for your account was just {escape(how)}.",
                                              "If this was you, no action is needed. If it wasn't, reset your password right away."])
    return f"Your {APP} password was {how}", text, html


def email_changed(user, new_address):
    text = (f"Hi {user.username},\n\nThe email address on your {APP} account was changed to {new_address}.\n"
            f"If this wasn't you, log in and reset your password right away.\n\n{APP}")
    html = _wrap("Your email address was changed",
                 [f"Hi {escape(user.username)}, the email on your account was changed to <strong>{escape(new_address)}</strong>.",
                  "If this wasn't you, log in and reset your password right away."])
    return f"The email on your {APP} account was changed", text, html


def test_message(user):
    text = f"Hi {user.username},\n\nThis is a test message from {APP}. If you can read it, email notifications are working.\n\n{APP}"
    html = _wrap("It works", [f"Hi {escape(user.username)}, this is a test message. Email notifications are working."])
    return f"Test message from {APP}", text, html


def _detail(item):
    extras = [x for x in (item.get("when"), item.get("minutes")) if x]
    return f"{item['project']}" + (f", {', '.join(extras)}" if extras else "")


def digest(user, tasks, deadlines, url, settings_url, extra_count=0):
    """每日摘要。tasks / deadlines 是 reminders.py 整理好的字典列表。"""
    total = len(tasks) + extra_count
    lines = [f"Good morning {user.username}.", ""]
    html_parts = [f"Good morning {escape(user.username)}."]
    if tasks:
        lines += [f"Tasks for today ({total}):"] + [f"- {t['title']} ({_detail(t)})" for t in tasks]
        if extra_count:
            lines.append(f"...and {extra_count} more.")
        lines.append("")
        items = "".join(f'<li style="margin:4px 0;">{escape(t["title"])} <span style="color:#6c6c76;">({escape(_detail(t))})</span></li>'
                        for t in tasks)
        more = f'<li style="color:#6c6c76;">...and {extra_count} more.</li>' if extra_count else ""
        html_parts.append(f'<strong>Tasks for today ({total})</strong><ul style="margin:8px 0 0;padding-left:20px;">{items}{more}</ul>')
    if deadlines:
        lines += ["Deadlines today:"] + [f"- {d['project']} at {d['time']}" for d in deadlines] + [""]
        items = "".join(f'<li style="margin:4px 0;">{escape(d["project"])} at {escape(d["time"])}</li>' for d in deadlines)
        html_parts.append(f'<strong>Deadlines today</strong><ul style="margin:8px 0 0;padding-left:20px;">{items}</ul>')
    lines += [f"Open your plan: {url}", "", f"Turn this off in Settings: {settings_url}"]
    subject = f"Today: {total} task{'s' if total != 1 else ''}" if tasks else "Today: deadline day"
    html = _wrap("Your day", html_parts, ("Open Today", url), "You get this because the daily summary is on. Change it in Settings, Notifications.")
    return subject, "\n".join(lines) + "\n", html


def deadline_reminder(user, items, url, settings_url):
    """截止日提醒。items: [{"project", "when"}]。"""
    n = len(items)
    lines = [f"Hi {user.username},", "", "Deadline reminder:"] + [f"- {i['project']}: {i['when']}" for i in items]
    lines += ["", f"Open your plan: {url}", "", f"Turn this off in Settings: {settings_url}"]
    li = "".join(f'<li style="margin:4px 0;"><strong>{escape(i["project"])}</strong>: {escape(i["when"])}</li>' for i in items)
    html = _wrap("Deadline reminder", [f"Hi {escape(user.username)}.", f'<ul style="margin:0;padding-left:20px;">{li}</ul>'],
                 ("Open my plan", url), "You get this because deadline reminders are on. Change it in Settings, Notifications.")
    subject = f"Deadline soon: {items[0]['project']}" if n == 1 else f"{n} deadlines coming up"
    return subject, "\n".join(lines) + "\n", html
