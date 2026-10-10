"""Tests for spark detection, driven by markup copied from the real page.

The fixtures below are not invented. `REAL_ROW` is the conversation row copied
out of DevTools on a logged-in https://www.douyin.com/chat, and `FLAME_VARIANTS`
are the three <img> elements from the user's own `fire.txt`. If the detector
regresses on these, it has regressed on production.
"""

from __future__ import annotations

import unittest

from dspark import analyze

FLAME_BASE = (
    "https://lf3-static.bytednsdoc.com/obj/eden-cn/tp_upfbvk/"
    "ljhwZthlaukjlkulzlp/flame_icon/normal/"
)

# Straight out of fire.txt, with the shared prefix restored.
FLAME_VARIANTS = (
    "normal_normal.png",
    "blue_normal.png",
    "gray_normal.png",
)

# Copied from DevTools on a logged-in /chat. A 129-day streak whose flame is
# grey — which is why grey must not be read as "no streak".
REAL_ROW = """
<div data-e2e="conversation-item" class="conversationConversationItemWrapper">
  <div class="conversationConversationItemrowArea1">
    <div class="commonIMAvataravatarContainer">
      <span class="semi-avatar semi-avatar-circle semi-avatar-medium semi-avatar-img"
            role="listitem" style="background-color: transparent; width: 50.4px;">
        <img src="https://p26.douyinpic.com/img/aweme-avatar/tos-cn-avt-0015_311c38.webp?biz_tag=aweme_im"
             draggable="false" class="">
      </span>
    </div>
  </div>
  <div class="conversationConversationItemrowArea2">
    <div class="conversationConversationItemtitleWrapper">
      <div class="conversationConversationItemtitle">张三</div>
      <div class="ConversationItemTagNextToTitlewrapper">
        <div class="ConversationItemTagNextToTitleleft">
          <div class="commonStreakstreakContainer" style="margin-left: 6px; margin-right: 6px;">
            <img class="commonStreakicon" src="{flame}" alt="">
            <div class="commonStreaknormalText"
                 style="color: var(--color-TextTertiary); transition: none;"> 129 </div>
          </div>
        </div>
        <div class="ConversationItemTagNextToTitleleft">
          <div class="ConversationItemTagNextToTitletimeStr">刚刚</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

# The same row with the streak container removed.
PLAIN_ROW = REAL_ROW.replace(
    """
        <div class="ConversationItemTagNextToTitleleft">
          <div class="commonStreakstreakContainer" style="margin-left: 6px; margin-right: 6px;">
            <img class="commonStreakicon" src="{flame}" alt="">
            <div class="commonStreaknormalText"
                 style="color: var(--color-TextTertiary); transition: none;"> 129 </div>
          </div>
        </div>""",
    "",
)


def row(flame: str = "gray_normal.png", name: str = "张三", days: int = 129) -> str:
    html = REAL_ROW.format(flame=FLAME_BASE + flame)
    return html.replace(">张三<", f">{name}<").replace("> 129 <", f"> {days} <")


def page(rows: list[str]) -> str:
    return (
        '<!DOCTYPE html><html><body><div class="chat">'
        + "".join(rows)
        + '</div><textarea placeholder="发送消息"></textarea></body></html>'
    )


def plain(name: str = "某人") -> str:
    """The same row with no streak container — a friend with no spark yet."""
    return PLAIN_ROW.format(flame=FLAME_BASE + "gray_normal.png").replace(
        ">张三<", f">{name}<"
    )


class RealMarkupTests(unittest.TestCase):
    """The fixtures are the specification."""

    def test_reads_the_spark_from_the_real_row(self) -> None:
        info = analyze.spark_info(analyze.parse(row()))
        self.assertTrue(info.present)
        self.assertEqual(info.days, 129)
        self.assertEqual(info.variant, "gray_normal.png")

    def test_reads_the_name_from_the_real_row(self) -> None:
        self.assertEqual(analyze.row_name(analyze.parse(row())), "张三")

    def test_reads_the_name_when_it_changes(self) -> None:
        html = row(name="张三")
        self.assertEqual(analyze.row_name(analyze.parse(html)), "张三")

    def test_grey_flame_still_counts_as_a_spark(self) -> None:
        """The trap: a 129-day streak renders grey. Grey is not 'no streak'."""
        info = analyze.spark_info(analyze.parse(row(flame="gray_normal.png")))
        self.assertTrue(info.present)

    def test_all_three_variants_are_recognised(self) -> None:
        for variant in FLAME_VARIANTS:
            with self.subTest(variant=variant):
                info = analyze.spark_info(analyze.parse(row(flame=variant)))
                self.assertTrue(info.present, f"{variant} not detected")
                self.assertEqual(info.variant, variant)

    def test_a_row_without_the_badge_reports_no_spark(self) -> None:
        html = PLAIN_ROW.format(flame=FLAME_BASE + "gray_normal.png")
        info = analyze.spark_info(analyze.parse(html))
        self.assertFalse(info.present)
        self.assertIsNone(info.days)

    def test_avatar_alone_is_not_mistaken_for_a_spark(self) -> None:
        """The avatar is also an <img> in the row; it must not count."""
        html = PLAIN_ROW.format(flame=FLAME_BASE + "gray_normal.png")
        self.assertFalse(analyze.spark_info(analyze.parse(html)).present)

    def test_day_count_of_one_digit_still_parses(self) -> None:
        info = analyze.spark_info(analyze.parse(row(days=7)))
        self.assertEqual(info.days, 7)

    def test_missing_day_count_does_not_crash(self) -> None:
        html = row().replace("> 129 <", "> <")
        info = analyze.spark_info(analyze.parse(html))
        self.assertTrue(info.present)
        self.assertIsNone(info.days)


class ListDetectionOnRealMarkupTests(unittest.TestCase):
    def test_finds_the_conversation_list(self) -> None:
        html = page([row(name=f"friend{i}", days=i) for i in range(6)])
        report = analyze.analyse(html)
        self.assertTrue(report.lists)
        self.assertEqual(len(report.lists[0].rows), 6)

    def test_the_list_scores_high_because_every_row_has_an_image(self) -> None:
        html = page([row(name=f"friend{i}") for i in range(6)])
        report = analyze.analyse(html)
        self.assertEqual(report.lists[0].image_ratio, 1.0)

    def test_the_badge_shows_up_as_a_partial_signature(self) -> None:
        """Some rows have a spark and some do not, so the badge is a partial."""
        html = page([row(name="a"), plain("b"), row(name="c")])
        report = analyze.analyse(html)
        signatures = [d.signature for d in report.differentiators]
        self.assertTrue(
            any("commonStreakicon" in s for s in signatures),
            f"badge not surfaced as a partial signature: {signatures}",
        )

    def test_three_variants_collapse_into_one_signature(self) -> None:
        """The fix that real data forced: key on class, not on src.

        normal/blue/gray_normal.png share `commonStreakicon`. Keying on the asset
        path split one badge into three signatures and scattered the evidence.
        """
        html = page(
            [
                row(flame="normal_normal.png", name="a"),
                row(flame="blue_normal.png", name="b"),
                row(flame="gray_normal.png", name="c"),
                plain("d"),
                plain("e"),
            ]
        )
        report = analyze.analyse(html)
        signatures = [d.signature for d in report.differentiators]
        flame_signatures = [s for s in signatures if "commonStreakicon" in s]
        self.assertEqual(
            len(flame_signatures),
            1,
            f"variants should collapse to one signature, got {flame_signatures}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
