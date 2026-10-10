"""Offline analysis of a dumped conversation page.

The message list needs a login, so its HTML can only come from the user's own
`probe` run. This module reads that HTML and works out the selectors without a
browser, which is far more reliable than eyeballing a screenshot:

  * which repeated block is the conversation list
  * **which element is the spark/streak badge**
  * where the composer is

The spark problem
-----------------
A spark badge is not identified by its name — Douyin hashes class names, and the
badge might be an `<img>`, an SVG, an icon-font glyph, or a number of days. What
makes it findable is its *distribution*: it appears in some conversation rows
and not in others. Every other part of a row (avatar, name, last message, time)
tends to be either in all rows or unique per row.

So the analysis ranks child signatures by "present in some rows but not all",
and prints the real markup of each, which is normally enough to spot the flame.

Nothing here is trusted blindly: every conclusion is printed with the counts and
a sample of actual HTML next to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator

from . import console, selectors

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

SPARK_WORDS = re.compile(
    r"streak|flame|spark|huohua|fire|hot|"
    r"火花|连火|连续",
    re.IGNORECASE,
)

COMPOSER_WORDS = re.compile(r"消息|发送|回复|message|send|reply|聊天", re.IGNORECASE)

_DIGITS = re.compile(r"\d+")


def normalise_asset(name: str) -> str:
    """Collapse an index or day count in a filename: `flame_7.png` -> `flame_N.png`.

    Deliberately conservative — digits only. Also collapsing hex hashes would
    make a per-user avatar URL and a shared badge asset collapse into the same
    signature, which would hide the very thing we are looking for.
    """
    return _DIGITS.sub("N", name)


# ---------------------------------------------------------------------------
# A small, tolerant DOM
# ---------------------------------------------------------------------------


class Node:
    __slots__ = ("tag", "attrs", "parent", "children", "chunks")

    def __init__(self, tag: str, attrs: list[tuple[str, str]], parent: "Node | None"):
        self.tag = tag
        self.attrs = {k: (v or "") for k, v in attrs}
        self.parent = parent
        self.children: list[Node] = []
        self.chunks: list[str] = []

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def own_text(self) -> str:
        return "".join(self.chunks).strip()

    def all_text(self) -> str:
        parts = [self.own_text()]
        for child in self.children:
            parts.append(child.all_text())
        return " ".join(p for p in parts if p).strip()

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def descendants(self) -> Iterator["Node"]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def ancestor_chain(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def signature(self) -> str:
        """A cheap identity for 'the same kind of element'.

        Deliberately never built from a full hashed class name, because those
        change on every deploy — matching them would produce a selector that
        breaks within a week.
        """
        e2e = self.attrs.get("data-e2e")
        if e2e:
            return f'[data-e2e="{e2e}"]'
        # Class before src for images. Real data forced this: the three flame
        # assets (normal/blue/gray_normal.png) share the class `commonStreakicon`,
        # so keying on src split one badge into three separate signatures and
        # scattered the evidence. `avatar-0.jpg` / `avatar-1.jpg` collapse the
        # same way.
        classes = self.classes
        if classes:
            return f"{self.tag}.{classes[0]}"
        if self.tag == "img":
            src = self.attrs.get("src") or ""
            name = src.rsplit("/", 1)[-1].split("?")[0]
            if name:
                return f'img[src*="{normalise_asset(name)}"]'
        if self.attrs.get("id"):
            return f'#{self.attrs["id"]}'
        return self.tag

    def css_path(self, max_depth: int = 4) -> str:
        """A short, readable path from the root."""
        parts: list[str] = []
        node: Node | None = self
        while node is not None and node.tag != "#document" and len(parts) < max_depth:
            parts.append(node.signature())
            node = node.parent
        return " > ".join(reversed(parts))

    def outer_html(self, limit: int = 220) -> str:
        """Opening tag plus a little context — enough to recognise the element."""
        bits = [f"<{self.tag}"]
        for key, value in self.attrs.items():
            if key in ("style",):
                continue
            bits.append(f' {key}="{value[:70]}"')
        opening = "".join(bits) + ">"
        inner = self.all_text()[:60]
        result = opening + inner
        return result[:limit]


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", [], None)
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        self.stack[-1].children.append(Node(tag, attrs, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].chunks.append(data)


def parse(html: str) -> Node:
    builder = TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# ---------------------------------------------------------------------------
# Reading a single conversation row
# ---------------------------------------------------------------------------


@dataclass
class SparkInfo:
    """What one conversation row says about its streak."""

    present: bool = False
    days: int | None = None
    variant: str | None = None
    src: str | None = None


def spark_info(row: Node) -> SparkInfo:
    """Read the spark badge out of one conversation row's DOM.

    Kept here, not in the browser layer, so it can be tested against the real
    markup without a login. The row looks like:

        <div data-e2e="conversation-item">
          <div class="commonStreakstreakContainer">
            <img class="commonStreakicon" src=".../flame_icon/normal/gray_normal.png">
            <div class="commonStreaknormalText"> 129 </div>
          </div>
        </div>

    Three independent hooks are accepted, because any one of them might be
    renamed: the container class, the image class, and the `flame_icon` segment
    of the asset path. A row counts as having a spark if any of them matches.
    """
    info = SparkInfo()

    for descendant in row.descendants():
        if descendant.tag != "img":
            continue
        src = descendant.attrs.get("src") or ""
        classes = descendant.classes
        if "commonStreakicon" in classes or selectors.SPARK_ASSET_MARKER in src:
            info.present = True
            info.src = src
            tail = src.rsplit("/", 1)[-1].split("?")[0]
            info.variant = tail or None
            break

    if info.present:
        for descendant in row.descendants():
            if "commonStreaknormalText" in descendant.classes:
                digits = re.sub(r"\D", "", descendant.all_text())
                if digits:
                    info.days = int(digits)
                break

    return info


def row_avatar(row: Node) -> str:
    """URL of the row's avatar — a stable identity for a friend.

    Needed because the conversation list is virtualised: a row's *index* changes
    as the list recycles nodes, so an index captured on one pass points at a
    different friend on the next. The avatar URL does not move.
    """
    for descendant in row.descendants():
        if descendant.tag != "img":
            continue
        src = descendant.attrs.get("src") or ""
        if not src:
            continue
        if "commonStreakicon" in descendant.classes:
            continue
        if selectors.SPARK_ASSET_MARKER in src:
            continue
        return src
    return ""


def row_name(row: Node) -> str:
    """The friend's display name in one conversation row.

    Prefers the title node. Falls back to the first scrap of text in the row,
    which is more durable than any class name — the row's own layout is far more
    likely to change than its "there is a name here" property.
    """
    for descendant in row.descendants():
        if any(
            "ConversationItemtitle" in cls and "Wrapper" not in cls
            for cls in descendant.classes
        ):
            text = descendant.all_text()
            if text:
                return text

    for descendant in row.descendants():
        if descendant.tag in ("span", "div", "p", "a"):
            text = descendant.own_text()
            if text:
                return text

    return "(unnamed)"


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class ListCandidate:
    container: Node
    rows: list[Node]
    score: float = 0.0
    image_ratio: float = 0.0
    text_ratio: float = 0.0
    richness: float = 0.0


@dataclass
class Differentiator:
    signature: str
    present_in: int
    total: int
    sample: str
    node: Node


@dataclass
class Composer:
    node: Node
    why: str


@dataclass
class Report:
    total_nodes: int
    lists: list[ListCandidate] = field(default_factory=list)
    differentiators: list[Differentiator] = field(default_factory=list)
    spark_like: list[Node] = field(default_factory=list)
    composers: list[Composer] = field(default_factory=list)
    used_rows: int = 0


MIN_ROWS = 3
MIN_SIMILARITY = 0.6


def _rows_of(node: Node) -> list[Node]:
    """Children that look like repeated siblings of one kind."""
    if len(node.children) < MIN_ROWS:
        return []
    counts: dict[str, list[Node]] = {}
    for child in node.children:
        counts.setdefault(child.signature(), []).append(child)
    signature, best = max(counts.items(), key=lambda kv: len(kv[1]))
    if len(best) / len(node.children) < MIN_SIMILARITY:
        return []
    return best


def find_lists(root: Node) -> list[ListCandidate]:
    found: list[ListCandidate] = []
    for node in root.walk():
        rows = _rows_of(node)
        if len(rows) < MIN_ROWS:
            continue

        # A conversation row contains text (a name) and usually an image.
        # "has any text at all" rather than "has more than one character": a
        # one-character nickname is perfectly legal.
        texted = sum(1 for row in rows if row.all_text())
        if texted / len(rows) < 0.6:
            continue

        imagem = sum(1 for row in rows if any(d.tag == "img" for d in row.walk()))
        image_ratio = imagem / len(rows)
        text_ratio = texted / len(rows)
        richness = sum(sum(1 for _ in row.descendants()) for row in rows) / len(rows)

        # Image ratio carries the most weight. A conversation list has an avatar
        # in every row; a panel of footer links (which also repeats, and also has
        # text) has one in almost none. Without this, the legal-notice block at
        # the bottom of douyin.com outranks the actual conversation list.
        score = len(rows) * (0.35 + image_ratio) * (0.30 + text_ratio)

        found.append(
            ListCandidate(
                container=node,
                rows=rows,
                score=score,
                image_ratio=image_ratio,
                text_ratio=text_ratio,
                richness=richness,
            )
        )

    found.sort(key=lambda c: c.score, reverse=True)
    return found[:5]


def find_differentiators(rows: list[Node]) -> list[Differentiator]:
    """Child signatures present in *some* rows but not all.

    This is the key to locating a spark badge: it is the one part of a row that
    is neither always there nor unique to a single row.
    """
    if not rows:
        return []

    total = len(rows)
    seen: dict[str, set[int]] = {}
    sample_nodes: dict[str, Node] = {}

    for index, row in enumerate(rows):
        for node in row.descendants():
            signature = node.signature()
            seen.setdefault(signature, set()).add(index)
            sample_nodes.setdefault(signature, node)

    partial: list[Differentiator] = []
    for signature, indexes in seen.items():
        count = len(indexes)
        if 0 < count < total:
            partial.append(
                Differentiator(
                    signature=signature,
                    present_in=count,
                    total=total,
                    sample=sample_nodes[signature].outer_html(),
                    node=sample_nodes[signature],
                )
            )

    # Two forces, in order:
    #   1. Repeats first. Something appearing in several rows is a shared piece
    #      of UI. Something appearing in exactly one row is usually that row's
    #      own content (its avatar URL, its message preview) and is noise.
    #   2. Then closest to half the rows, because a badge is neither universal
    #      nor rare.
    partial.sort(key=lambda d: (d.present_in < 2, abs(d.present_in / d.total - 0.5)))
    return partial


def find_spark_like(root: Node) -> list[Node]:
    """Anything whose attributes or markup literally mention a spark or flame."""
    hits: list[Node] = []
    for node in root.walk():
        haystack = " ".join(
            [
                node.tag,
                node.attrs.get("class", ""),
                node.attrs.get("data-e2e", ""),
                node.attrs.get("src", ""),
                node.attrs.get("alt", ""),
                node.attrs.get("title", ""),
                node.attrs.get("aria-label", ""),
                node.own_text(),
            ]
        )
        if node.tag in ("svg", "script", "style", "path"):
            continue
        if SPARK_WORDS.search(haystack):
            hits.append(node)
    return hits[:40]


def find_composers(root: Node) -> list[Composer]:
    found: list[Composer] = []
    for node in root.walk():
        if node.tag == "textarea":
            found.append(Composer(node, "textarea"))
        elif node.tag == "input" and node.attrs.get("type", "text") in ("text", ""):
            found.append(Composer(node, "text input"))
        elif node.attrs.get("contenteditable") == "true":
            found.append(Composer(node, "contenteditable"))
        else:
            placeholder = node.attrs.get("placeholder") or ""
            if placeholder and COMPOSER_WORDS.search(placeholder):
                found.append(Composer(node, f'placeholder="{placeholder}"'))
    return found[:12]


def analyse(html: str) -> Report:
    root = parse(html)
    report = Report(total_nodes=sum(1 for _ in root.walk()))

    report.lists = find_lists(root)
    if report.lists:
        best = report.lists[0]
        report.used_rows = len(best.rows)
        report.differentiators = find_differentiators(best.rows)

    report.spark_like = find_spark_like(root)
    report.composers = find_composers(root)
    return report


def load(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def newest_probe(directory: Path) -> Path | None:
    files = sorted(directory.glob("probe-*.html"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def run(html_path: Path | None = None) -> int:
    """The `analyze` command: work out selectors from a dumped page, offline."""
    console.step("Analyse")

    if html_path is None:
        html_path = newest_probe(Path("diagnostics"))
        if html_path is None:
            console.error("No probe-*.html in diagnostics/.")
            console.info("Run `python -m dspark probe` first - it needs a login.")
            return 1

    if not html_path.exists():
        console.error(f"Not found: {html_path}")
        return 1

    console.info(f"file : {html_path}")
    report = analyse(load(html_path))

    for line in summarise(report):
        print(line)

    if not report.lists:
        console.info("")
        console.warn("No repeated row structure found.")
        console.info("Either this is not the message page, or you were logged out.")

    return 0


def summarise(report: Report) -> Iterable[str]:
    """The human-readable half, kept separate so tests can drive `analyse` alone."""
    yield f"parsed {report.total_nodes:,} nodes"

    yield ""
    yield "conversation list candidates"
    if not report.lists:
        yield "  none found - is this the message page, and is it logged in?"
    for index, candidate in enumerate(report.lists, start=1):
        sample = candidate.rows[0].all_text()[:70]
        yield (
            f"  {index}. {len(candidate.rows)} rows"
            f"   images {candidate.image_ratio:.0%}"
            f"   text {candidate.text_ratio:.0%}"
            f"   nodes/row {candidate.richness:.0f}"
        )
        yield f"     {candidate.container.css_path(5)}"
        yield f"     first row text: {sample!r}"

    if report.differentiators:
        yield ""
        yield f"present in SOME rows but not all ({report.used_rows} rows)"
        yield "  <- the spark badge is in here"
        for item in report.differentiators[:14]:
            yield f"  {item.present_in}/{item.total} rows  {item.signature}"
            yield f"        {item.sample}"

    if report.spark_like:
        yield ""
        yield "elements whose markup literally mentions a spark"
        for node in report.spark_like[:10]:
            yield f"  {node.css_path(4)}"
            yield f"        {node.outer_html(160)}"

    yield ""
    yield "composer candidates"
    if not report.composers:
        yield "  none found"
    for composer in report.composers:
        yield f"  <{composer.node.tag}>  {composer.why}"
        yield f"        {composer.node.css_path(4)}"
