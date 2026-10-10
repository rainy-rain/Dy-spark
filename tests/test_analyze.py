"""Tests for the offline HTML analyser.

These run on synthetic markup that imitates the shape of a Douyin conversation
list: several rows, all with an avatar, a name and a preview, and only *some*
with a spark badge. Finding that badge from its distribution alone is the whole
point of the module, so it is worth pinning down.

A real logged-in page would be better evidence, but this at least proves the
heuristic works on the structure it claims to handle.
"""

from __future__ import annotations

import unittest

from dspark import analyze


def conversation_row(index: int, name: str, *, spark: bool, spark_kind: str = "img") -> str:
    badge = ""
    if spark and spark_kind == "img":
        # Real markup uses a readable class here, which is what makes the three
        # flame assets collapse into one signature.
        badge = '<img class="commonStreakicon" src="//p3.douyinpic.com/obj/flame.png">'
    elif spark and spark_kind == "font":
        badge = '<div class="icon-huohua"></div>'
    elif spark and spark_kind == "days":
        badge = '<span class="x3">7天</span>'
    return f"""
      <div data-e2e="conversation-item" class="hash{index}">
        <img class="avatar" src="//p3.douyinpic.com/obj/avatar-{index}.jpg">
        <div class="name"> {name} </div>
        <div class="preview"> last message {index} </div>
        <div class="time"> 昨天 </div>
        {badge}
      </div>"""


def page(rows: str) -> str:
    return f"""<!DOCTYPE html><html><body>
    <div class="app">
      <div data-e2e="conversation-list" class="list">
{rows}
      </div>
      <textarea data-e2e="message-input" placeholder="发送消息"></textarea>
    </div>
    </body></html>"""


class SparkDetectionTests(unittest.TestCase):
    def test_finds_the_list(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        report = analyze.analyse(page(rows))
        self.assertTrue(report.lists, "no conversation list found")
        self.assertEqual(len(report.lists[0].rows), 6)

    def test_spark_img_is_reported_as_present_in_some_rows(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        report = analyze.analyse(page(rows))

        by_signature = {d.signature: d for d in report.differentiators}
        self.assertIn("img.commonStreakicon", by_signature)
        found = by_signature["img.commonStreakicon"]
        self.assertEqual(found.total, 6)
        self.assertEqual(found.present_in, 3, "3 of 6 rows carry the badge")

    def test_avatars_are_not_offered_as_spark_candidates(self) -> None:
        """The trap: every avatar URL differs per row, so a naive analysis
        reports six 'partial' signatures and buries the badge."""
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        report = analyze.analyse(page(rows))
        signatures = [d.signature for d in report.differentiators]

        # Digits are normalised, so the six avatars collapse into one signature
        # that is present in *every* row - and is therefore not a partial at all.
        self.assertNotIn('img[src*="avatar-N.jpg"]', signatures)
        self.assertFalse(
            any("avatar" in s for s in signatures),
            f"avatar variants leaked into the candidates: {signatures}",
        )

    def test_repeats_rank_above_one_row_oddities(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        report = analyze.analyse(page(rows))
        self.assertTrue(report.differentiators)
        first = report.differentiators[0]
        self.assertGreaterEqual(
            first.present_in,
            2,
            "a signature seen in only one row should not outrank a repeated one",
        )

    def test_day_count_variants_collapse_together(self) -> None:
        """flame_3.png and flame_7.png are the same badge, not two."""
        rows = (
            '<div data-e2e="conversation-item"><img class="a" src="/avatar-0.jpg">'
            '<div class="name">a</div><img class="commonStreakicon" src="/flame_3.png"></div>'
            '<div data-e2e="conversation-item"><img class="a" src="/avatar-1.jpg">'
            '<div class="name">b</div><img class="commonStreakicon" src="/flame_7.png"></div>'
            '<div data-e2e="conversation-item"><img class="a" src="/avatar-2.jpg">'
            '<div class="name">c</div></div>'
        )
        report = analyze.analyse(page(rows))
        signatures = [d.signature for d in report.differentiators]
        badge = [s for s in signatures if "commonStreakicon" in s]
        self.assertEqual(
            len(badge), 1,
            f"the two day counts should collapse to one signature, got {signatures}",
        )

    def test_works_when_the_badge_is_an_icon_font_class(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i < 2), spark_kind="font")
            for i in range(5)
        )
        report = analyze.analyse(page(rows))
        signatures = {d.signature for d in report.differentiators}
        self.assertIn("div.icon-huohua", signatures)

    def test_works_when_the_badge_is_a_day_count(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i == 1), spark_kind="days")
            for i in range(4)
        )
        report = analyze.analyse(page(rows))
        self.assertTrue(report.differentiators, "expected the 7天 span to stand out")

    def test_literal_spark_words_are_surfaced(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        report = analyze.analyse(page(rows))
        self.assertTrue(report.spark_like, "flame.png in src should be surfaced")

    def test_no_spark_anywhere_means_no_spark_hits(self) -> None:
        rows = "".join(conversation_row(i, f"friend{i}", spark=False) for i in range(5))
        report = analyze.analyse(page(rows))
        self.assertEqual(report.spark_like, [])


class ComposerTests(unittest.TestCase):
    def test_finds_the_textarea(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=False) for i in range(4)
        )
        report = analyze.analyse(page(rows))
        tags = {c.node.tag for c in report.composers}
        self.assertIn("textarea", tags)

    def test_finds_a_contenteditable_composer(self) -> None:
        html = """
        <html><body>
          <div data-e2e="conversation-list">
            <div data-e2e="conversation-item"><div class="n">a</div></div>
            <div data-e2e="conversation-item"><div class="n">b</div></div>
            <div data-e2e="conversation-item"><div class="n">c</div></div>
          </div>
          <div contenteditable="true" class="editor"></div>
        </body></html>
        """
        report = analyze.analyse(html)
        self.assertTrue(
            any(c.why == "contenteditable" for c in report.composers),
            "contenteditable composer not found",
        )


class RobustnessTests(unittest.TestCase):
    def test_survives_unclosed_tags(self) -> None:
        html = (
            '<div data-e2e="conversation-list">'
            '<div data-e2e="conversation-item"><div>a'
            '<div data-e2e="conversation-item"><div>b'
            '<div data-e2e="conversation-item"><div>c'
            "<img src='/flame.png'>"
        )
        report = analyze.analyse(html)
        self.assertGreater(report.total_nodes, 0)

    def test_empty_html_does_not_crash(self) -> None:
        report = analyze.analyse("")
        self.assertEqual(report.lists, [])
        self.assertEqual(report.composers, [])

    def test_summary_is_renderable(self) -> None:
        rows = "".join(
            conversation_row(i, f"friend{i}", spark=(i % 2 == 0)) for i in range(6)
        )
        lines = list(analyze.summarise(analyze.analyse(page(rows))))
        text = "\n".join(lines)
        self.assertIn("conversation list candidates", text)
        self.assertIn("flame.png", text)
        self.assertIn("composer candidates", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
