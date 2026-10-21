"""Tiny HTML helpers so route tests can ask "what does the page say?"
instead of matching exact markup, attribute order or spacing.

Usage:
    page = parse(response.get_data(as_text=True))
    page.find("table", cls="txn-table")
    form_state(page.find("form"))
"""

from html.parser import HTMLParser

_VOID_TAGS = {"meta", "link", "input", "br", "hr", "img"}


class Element:
    def __init__(self, tag, attrs, parent=None):
        self.tag = tag
        self.attrs = {key: (value if value is not None else "") for key, value in attrs}
        self.parent = parent
        self.children = []
        self._text = []

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def classes(self):
        return self.attrs.get("class", "").split()

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def text(self):
        """All the text inside this element, with whitespace collapsed."""
        parts = list(self._text)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def find_all(self, tag=None, cls=None, **attrs):
        """Find descendants by tag, CSS class and attributes (underscores become hyphens)."""
        wanted = {key.replace("_", "-"): value for key, value in attrs.items()}
        matches = []
        for element in list(self.iter())[1:]:
            if tag and element.tag != tag:
                continue
            if cls and cls not in element.classes:
                continue
            if any(element.attrs.get(key) != value for key, value in wanted.items()):
                continue
            matches.append(element)
        return matches

    def find(self, tag=None, cls=None, **attrs):
        matches = self.find_all(tag, cls, **attrs)
        return matches[0] if matches else None


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("document", [])
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs, self.current)
        self.current.children.append(element)
        if tag not in _VOID_TAGS:
            self.current = element

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current._text.append(data)


def parse(html):
    builder = _Builder()
    builder.feed(html)
    return builder.root


def form_state(form):
    """What a browser would submit for this form: {field name: value}."""
    state = {}
    for field in form.find_all("input"):
        name, kind = field.get("name"), field.get("type", "text")
        if not name:
            continue
        if kind == "radio":
            if "checked" in field.attrs:
                state[name] = field.get("value", "")
            else:
                state.setdefault(name, "")
        elif kind in ("checkbox", "submit"):
            continue
        else:
            state[name] = field.get("value", "")
    for select in form.find_all("select"):
        chosen = [option for option in select.find_all("option") if "selected" in option.attrs]
        state[select.get("name")] = chosen[0].get("value", "") if chosen else ""
    return state


def table_rows(table):
    """Each body row as {column header: cell text}."""
    headers = [th.text() for th in table.find("thead").find_all("th")]
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = [cell for cell in tr.children if cell.tag in ("td", "th")]
        rows.append({header: cell.text() for header, cell in zip(headers, cells)})
    return rows


def stats(page):
    """The dashboard's headline figures as {label: value}."""
    box = page.find("dl", cls="stats")
    return {item.find("dt").text(): item.find("dd").text() for item in box.find_all("div")}
