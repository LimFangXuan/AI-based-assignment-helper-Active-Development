"""演示模式下代替 OpenAlex 的离线样本：同样的接口格式，由 httpx.MockTransport 返回，所以走的是真实的解析代码。

论文、作者和期刊都是虚构的示例；DOI 用的是专门留给示例的 10.5555 前缀，链接指向 example.org。
"""
import httpx

PAPERS = [
    ("Planning habits and assignment completion among first-year students", ["Aisha Rahman", "Daniel Ong"], 2023,
     "Journal of Student Success", "Students who split assignments into dated tasks submitted on time more often than those who planned by deadline only."),
    ("Feedback loops in academic writing: a classroom study", ["Priya Nair", "Tom Hayes", "Mei Chen"], 2022,
     "Writing in Higher Education", "Short cycles of drafting and feedback improved structure and argument quality in undergraduate reports."),
    ("Clarifying assessment criteria to reduce student anxiety", ["Grace Okafor", "Lukas Brandt"], 2021,
     "Assessment and Learning", "Checklists derived from marking rubrics reduced reported anxiety and improved alignment with the criteria."),
    ("Digital tools for self-regulated learning: a review", ["Hana Suzuki", "Omar Haddad"], 2024,
     "Educational Technology Review", "Reviews forty studies on planning and reminder tools and their effect on self-regulated learning."),
    ("Source evaluation skills in undergraduate research", ["Elena Rossi", "Kwame Mensah"], 2020,
     "Information Literacy Quarterly", "Students who practised checking sources cited fewer unreliable references in later assignments."),
    ("Time-on-task and deadline effects in coursework", ["Sofia Lindqvist", "Arjun Patel"], 2019,
     "Studies in Learning Behaviour", "Work clustered in the final two days before deadlines; spreading tasks out improved grades modestly."),
]


def _inverted(text):
    index = {}
    for position, word in enumerate(text.split()):
        index.setdefault(word, []).append(position)
    return index


def works():
    return [{
        "id": f"https://openalex.org/W90000{i}", "title": title, "publication_year": year, "is_retracted": False, "is_paratext": False,
        "authorships": [{"author": {"display_name": name}} for name in authors],
        "primary_location": {"landing_page_url": f"https://example.org/demo-paper-{i}", "source": {"display_name": venue}},
        "open_access": {"is_oa": True, "oa_url": f"https://example.org/demo-paper-{i}.pdf"},
        "doi": f"https://doi.org/10.5555/demo.{i}", "cited_by_count": 40 - 5 * i, "type": "article",
        "biblio": {"volume": str(10 + i), "issue": "2", "first_page": str(10 * i + 1), "last_page": str(10 * i + 12)},
        "abstract_inverted_index": _inverted(abstract),
    } for i, (title, authors, year, venue, abstract) in enumerate(PAPERS, 1)]


def handler(request):
    return httpx.Response(200, json={"results": works()})
