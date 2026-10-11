"""只负责和 OpenAlex 通信：检索论文、整理字段、还原摘要。不碰数据库，也不碰 AI。

OpenAlex 是一个开放的学术数据库。自 2026 年 2 月起必须使用（免费的）API key。
key 放在请求头 Authorization 里，不放进网址，避免出现在日志中。
"""
import logging
import os
import re

import httpx
from dotenv import load_dotenv

from . import demo_mode, demo_papers

load_dotenv()

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx 的请求日志会记录完整网址，调低级别更保险

BASE_URL = "https://api.openalex.org"
TIMEOUT_SECONDS = float(os.getenv("OPENALEX_TIMEOUT_SECONDS", "20"))
MAX_ABSTRACT_CHARS = 1500


class OpenAlexError(Exception):
    """检索失败。user_message 可以直接显示给用户。"""

    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


def _http_client():
    """单独成函数：测试时替换成 httpx.MockTransport，就不会发出真实请求。"""
    if demo_mode.enabled():  # 作品集演示：离线样本论文，不连 OpenAlex
        return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(demo_papers.handler))
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SECONDS)


def short_id(value):
    """把 'https://openalex.org/W123'、'w123'、' W123 ' 统一成 'W123'；不合法返回空字符串。

    AI 可能返回完整网址形式的 ID，而候选里存的是短 ID，不统一就会把正确的推荐误判为编造。
    """
    text = str(value or "").strip().rstrip("/").split("/")[-1].upper()
    return text if re.fullmatch(r"W\d+", text) else ""


def reconstruct_abstract(inverted_index):
    """把倒排索引还原成摘要文本。

    倒排索引的形式是 {"词": [出现的位置, ...]}，例如 {"Deep": [0], "learning": [1, 5]}。
    做法：建立“位置 → 词”的对应，再按位置从小到大连起来。
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    words_by_position = {}
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                words_by_position[position] = str(word)
    return " ".join(words_by_position[p] for p in sorted(words_by_position))


def _safe_url(url):
    """只接受 http/https 链接，防止 javascript: 之类的链接被放进页面。"""
    url = str(url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else None


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_work(raw):
    """把 OpenAlex 的一条原始结果整理成我们需要的字段；不合格的返回 None。

    所有字段都可能缺失，所以一律用 .get()。撤稿论文和封面、目录之类的“非正文”直接丢弃。
    """
    if not isinstance(raw, dict):
        return None
    work_id = short_id(raw.get("id"))
    title = str(raw.get("title") or raw.get("display_name") or "").strip()
    if not work_id or not title or raw.get("is_retracted") or raw.get("is_paratext"):
        return None

    location = raw.get("primary_location") or {}
    source = location.get("source") or {}
    open_access = raw.get("open_access") or {}
    biblio = raw.get("biblio") or {}

    names = []
    for authorship in raw.get("authorships") or []:
        if isinstance(authorship, dict):
            name = (authorship.get("author") or {}).get("display_name") or authorship.get("raw_author_name")
            if name:
                names.append(str(name).strip())

    first_page, last_page = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{first_page}-{last_page}" if first_page and last_page else (first_page or None)
    doi = str(raw.get("doi") or "").strip() or None

    return {
        "openalex_id": work_id,
        "title": title[:500],
        "authors": (", ".join(names[:3]) + (" et al." if len(names) > 3 else ""))[:500],
        "author_list": names[:20],
        "year": _int_or_none(raw.get("publication_year")),
        "venue": (str(source.get("display_name") or "").strip()[:300]) or None,
        "doi": doi[:200] if doi else None,
        "url": _safe_url(location.get("landing_page_url")) or _safe_url(doi),
        "oa_url": _safe_url(open_access.get("oa_url")),
        "is_oa": bool(open_access.get("is_oa")),
        "cited_by_count": _int_or_none(raw.get("cited_by_count")) or 0,
        "work_type": str(raw.get("type") or "")[:40] or None,
        "volume": str(biblio.get("volume") or "")[:20] or None,
        "issue": str(biblio.get("issue") or "")[:20] or None,
        "pages": str(pages)[:40] if pages else None,
        "abstract": reconstruct_abstract(raw.get("abstract_inverted_index"))[:MAX_ABSTRACT_CHARS],
    }


def search_works(query, per_page=15, oa_only=True):
    """用一组检索词检索论文，返回整理好的候选列表。

    oa_only=True 时只要开放获取的论文：先用官方的过滤参数，拿回结果后代码再检查一次。
    """
    api_key = os.getenv("OPENALEX_API_KEY") or ("offline-demo" if demo_mode.enabled() else "")
    if not api_key:
        raise OpenAlexError("Paper search is not set up yet (missing OpenAlex API key). Please contact the administrator.")

    params = {"search": query, "per_page": max(1, min(int(per_page), 100))}
    if oa_only:
        params["filter"] = "open_access.is_oa:true"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with _http_client() as client:
            response = client.get("/works", params=params, headers=headers)
    except httpx.TimeoutException as e:
        logger.warning("OpenAlex 请求超时（超过 %s 秒）", TIMEOUT_SECONDS)
        raise OpenAlexError("The paper search timed out. Please try again later.") from e
    except httpx.HTTPError as e:
        logger.warning("连接 OpenAlex 失败：%s", type(e).__name__)
        raise OpenAlexError("Could not reach the paper database. Check your network connection and try again.") from e

    if response.status_code != 200:
        # 只记状态码和响应内容的开头，不记网址和请求头
        logger.warning("OpenAlex 返回 %s：%s", response.status_code, response.text[:300])
        if response.status_code in (401, 403):
            message = "The paper search was refused; the OpenAlex API key may be invalid. Please contact the administrator."
        elif response.status_code == 429:
            message = "Too many paper searches, or today's free quota is used up. Please try again later."
        else:
            message = "The paper database is temporarily unavailable. Please try again later."
        raise OpenAlexError(message)

    try:
        data = response.json()
    except ValueError as e:
        raise OpenAlexError("The paper database returned something unexpected. Please try again later.") from e
    results = data.get("results") if isinstance(data, dict) else None

    works = [w for w in (normalize_work(r) for r in results or []) if w]
    if oa_only:
        works = [w for w in works if w["is_oa"]]
    return works
