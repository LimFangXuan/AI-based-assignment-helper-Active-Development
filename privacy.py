"""发送给 AI 之前，遮掉文本里的邮箱和电话号码。

只处理能可靠识别的两类信息。地址、身份证号等无法可靠识别，仍需用户自己注意，页面上会提醒。
数据库里保存的仍是用户原文；只有发给 AI 的内容和生成的 prompt 会被遮掉。
"""
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 候选电话：可选的 +，数字开头和结尾，中间可以有空格、横线、括号
PHONE_CANDIDATE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s\-()]{7,}\d(?![\w.])")
DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def _is_phone(candidate):
    digits = re.sub(r"\D", "", candidate)
    if not 9 <= len(digits) <= 15:
        return False
    if DATE_RE.search(candidate):  # 例如 "2026-10-12 23:59" 不是电话
        return False
    return candidate.startswith(("+", "0")) or len(digits) >= 10


def redact(text):
    """返回遮掉邮箱和电话后的文本。"""
    if not text:
        return text or ""
    text = EMAIL_RE.sub("[邮箱已隐藏]", text)
    return PHONE_CANDIDATE_RE.sub(lambda m: "[电话已隐藏]" if _is_phone(m.group()) else m.group(), text)
