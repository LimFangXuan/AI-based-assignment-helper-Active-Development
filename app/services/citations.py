"""引用格式：完全根据 OpenAlex 的元数据由代码生成，不经过 AI，所以不会编造。

支持 APA 7、Harvard、IEEE、MLA、Chicago（作者-年份）。没选或选了 “Follow the guideline / Not required”
时用 APA 7，并在页面上提示学生按 guideline 核对。
"""

AUTHOR_YEAR = ("apa7", "harvard", "chicago")


def _surname(name):
    parts = str(name or "").replace(",", " ").split()
    return parts[-1] if parts else "Anon."


def in_text(paper, style, number=None):
    """正文里的引用标记，例如 (Tan & Lee, 2021) / [3] / (Tan)。"""
    if style == "ieee":
        return f"[{number}]"
    names = paper.author_list or []
    if not names:
        who = (paper.title or "Untitled")[:40]
    elif len(names) == 1:
        who = _surname(names[0])
    elif len(names) == 2:
        who = f"{_surname(names[0])} {'and' if style in ('mla', 'chicago', 'harvard') else '&'} {_surname(names[1])}"
    else:
        who = f"{_surname(names[0])} et al."
    year = paper.year or "n.d."
    if style == "mla":
        return f"({who})"
    if style == "chicago":
        return f"({who} {year})"
    return f"({who}, {year})"


def _venue_tail(paper):
    venue = paper.venue or ""
    if venue and paper.volume:
        venue += f", {paper.volume}"
        if paper.issue:
            venue += f"({paper.issue})"
    if venue and paper.pages:
        venue += f", {paper.pages}"
    return venue


def _link(paper):
    if paper.doi:
        return paper.doi if paper.doi.startswith("http") else f"https://doi.org/{paper.doi}"
    return paper.url or ""


def reference(paper, style="apa7", number=None):
    """参考文献列表里的一条。"""
    names = paper.author_list or []
    title = (paper.title or "").rstrip(".")
    year = paper.year or "n.d."
    link = _link(paper)
    if style == "ieee":
        authors = ", ".join(f"{n.split()[0][0]}. {_surname(n)}" if len(n.split()) > 1 else n for n in names[:6])
        if len(names) > 6:
            authors += " et al."
        parts = [f"[{number}] {authors or 'Anon.'}, “{title},”"]
        if paper.venue:
            parts.append(f"{paper.venue},")
        if paper.volume:
            parts.append(f"vol. {paper.volume},")
        if paper.issue:
            parts.append(f"no. {paper.issue},")
        if paper.pages:
            parts.append(f"pp. {paper.pages},")
        parts.append(f"{year}.")
        if link:
            parts.append(link)
        return " ".join(parts)
    if style == "mla":
        authors = names[0] if len(names) == 1 else (f"{names[0]}, et al." if names else "Anon.")
        return " ".join(x for x in [f"{authors}. “{title}.”", f"{_venue_tail(paper)}," if paper.venue else "",
                                    f"{year}.", link] if x)
    # APA 7（默认）/ Harvard / Chicago 作者-年份格式都以“作者（年份）标题”开头，这里用 APA 的写法
    if not names:
        authors = "Anon."
    elif len(names) == 1:
        authors = names[0]
    elif len(names) == 2:
        authors = f"{names[0]} & {names[1]}"
    elif len(names) <= 20:
        authors = ", ".join(names[:-1]) + ", & " + names[-1]
    else:
        authors = ", ".join(names[:19]) + ", ... " + names[-1]
    parts = [f"{authors} ({year}). {title}."]
    if paper.venue:
        parts.append(_venue_tail(paper) + ".")
    if link:
        parts.append(link)
    return " ".join(parts)


def format_citation(paper):
    """论文详情页上的 APA 引用。"""
    return reference(paper, "apa7")
