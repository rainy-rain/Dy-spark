"""Every Douyin DOM selector lives in this one file.

How these were established
--------------------------
Not by guessing. Two rounds of reading the real thing:

  * a live, logged-out douyin.com was dumped and searched directly
  * the conversation row markup was copied out of DevTools on a logged-in
    `/chat`, and the flame element pasted into `fire.txt`

What that showed:

  * Douyin runs **two** naming systems. Layout uses hashed CSS-module names
    (`VQdYTqcZ`, `iO_wmpM6`) that change every deploy. Feature-level pieces use
    readable names (`commonStreakicon`, `conversation-item`) that are stable.
    So class names are not useless — *hashed* ones are. Prefer `data-e2e`, then
    a readable class, and never a hash.
  * Conversation rows carry `data-e2e="conversation-item"`. Confirmed.
  * The spark badge is an `<img class="commonStreakicon">` whose asset path
    literally contains `flame_icon`, with the streak length in a sibling
    `commonStreaknormalText`.

Verified here is marked VERIFIED. The composer is still unverified: it was not
in the material provided, so it remains a guess. `python -m dspark pick` will
settle it in one click.
"""

from __future__ import annotations

# ==========================================================================
# Chat page — VERIFIED from DevTools on a logged-in /chat
# ==========================================================================

# Confirmed on a real row: <div data-e2e="conversation-item" ...>
CONVERSATION_ITEM = '[data-e2e="conversation-item"]'

# Proves the list rendered, and doubles as the arrival check for _goto_messages.
MESSAGE_LIST = (
    '[data-e2e="conversation-item"], '
    '[data-e2e="conversation-list"], '
    '[class*="conversationConversationItemWrapper"]'
)

# <div class="conversationConversationItemtitle">张三</div>
CONVERSATION_NAME = (
    '[class*="ConversationItemtitle"]:not([class*="Wrapper"]), '
    '[data-e2e="conversation-name"]'
)

# The streak badge, three independent hooks:
#   <div class="commonStreakstreakContainer">
#     <img class="commonStreakicon" src=".../flame_icon/normal/gray_normal.png">
#     <div class="commonStreaknormalText"> 129 </div>
#   </div>
SPARK_BADGE = (
    "div.commonStreakstreakContainer, "
    "img.commonStreakicon, "
    'img[src*="flame_icon"]'
)

# The streak length, as days.
SPARK_DAYS = "div.commonStreaknormalText, [class*='commonStreaknormalText']"

# The three asset variants seen so far. The middle segment is the colour; the
# suffix is the state. A grey flame on a 129-day streak is the *normal* list
# appearance, not an absent streak - so all three count unless configured
# otherwise.
SPARK_ASSET_MARKER = "flame_icon"

# ==========================================================================
# Home page — VERIFIED against live douyin.com
# ==========================================================================

# The 消息 (Messages) button in the top bar:
#   <div data-e2e="im-entry"><div><div data-e2e="something-button">
#     <div><i></i></div><p>消息</p></div></div></div>
#
# Careful: clicking this while logged out does NOT raise - Douyin silently
# bounces you to the featured feed. `_goto_messages` confirms arrival instead of
# trusting the click.
MESSAGE_ENTRY = '[data-e2e="im-entry"]'

# Present only while signed out; matches on text because the class is hashed
# (<p class="VQdYTqcZ">登录</p>).
#
# The last two entries were added after seeing the real /chat page: it renders a
# modal reading 登录后免费畅享高清视频 with a 扫码登录 QR code, on top of a chat
# layout full of loading skeletons. Without these, a logged-out /chat looks like
# a chat page that simply has not loaded yet.
LOGGED_OUT_HINT = (
    'button:has-text("登录"), '
    'button:has-text("立即登录"), '
    "text=扫码登录, "
    "text=登录后免费畅享高清视频, "
    '[data-e2e="login-button"]'
)

# ==========================================================================
# Composer — VERIFIED from DevTools on a logged-in /chat
# ==========================================================================

# The container carries a data-e2e, and the editable inside is a Slate editor:
#
#   <div data-e2e="msg-input" class="messageMsgInputcontainer">
#     <div class="messageMsgInputinputRow">
#       <div class="zone-container editor-kit-container messageEditorinputArea ..."
#            data-slate-editor="true" contenteditable="true"
#            data-placeholder="发送消息">
#         <div class="ace-line" ...><span data-leaf="true">&#8203;</span></div>
#
# That is a Slate.js editor, not a textarea, and it changes three things:
#   * fill() will not work — Slate is not an <input>. Click it, then send real
#     key events.
#   * an empty editor still contains a zero-width space (U+200B), which JS's
#     String.trim() does NOT remove. "Is it empty?" has to strip it explicitly,
#     or every successful send looks like a failure.
MESSAGE_INPUT = (
    'div[data-e2e="msg-input"] [data-slate-editor="true"], '
    'div[data-slate-editor="true"][contenteditable="true"], '
    'div[contenteditable="true"][data-placeholder], '
    'div[contenteditable="true"]'
)

# Only used if Enter does not send.
#
# VERIFIED from DevTools — and it corrected a real mistake. The control is an
# <svg>, not a <button>:
#
#   <svg width="36" height="36" fill="none" viewBox="4 5 27 27"
#        class="messageMsgInputpublishBtn e2e-send-send-msg-btn">…</svg>
#
# The earlier version looked for `button` elements inside the input row and so
# could never have matched anything: the fallback path was dead code that would
# have failed silently if Enter had ever stopped working.
SEND_BUTTON = (
    "svg.e2e-send-send-msg-btn, "
    "svg.messageMsgInputpublishBtn, "
    '[class~="e2e-send-send-msg-btn"], '
    '[class~="messageMsgInputpublishBtn"], '
    'div[data-e2e="msg-input"] button, '
    '[data-e2e="message-send"]'
)

# ==========================================================================
# Emoji panel — VERIFIED from DevTools on a logged-in /chat
# ==========================================================================

# The 😀 button that opens the panel, in the same action row as the file
# uploader and the send button:
#
#   <div class="messageMsgInputinputAction">
#     <div class="semi-upload MsgInputFileuploadim-saas-fileUploader">…</div>
#     <svg class="messageMsgInputiconAction">…</svg>                      <- this
#     <svg class="messageMsgInputpublishBtn e2e-send-send-msg-btn">…</svg>
#   </div>
EMOJI_BUTTON = (
    'div[data-e2e="msg-input"] svg[class~="messageMsgInputiconAction"], '
    'svg[class~="messageMsgInputiconAction"], '
    '[class~="messageMsgInputiconAction"]'
)

# The panel that opens. Every item carries a *text* label, which is what makes
# picking one robust instead of positional:
#
#   <div class="componentsemojiemojiPanel">
#     <div class="componentsemojiTabPanel">…</div>
#     <div class="emojiEmojiItememojiItem">
#       <div class="emojiEmojiItememojiImgBox" data-apm-action="EmojiItem">
#         <img class="commonMyImageimgReal" src="…">
#       </div>
#       <div class="emojiEmojiItememojiItemDesc">续火花</div>
#     </div>
#   </div>
#
# `[class~=...]` (exact word) rather than `[class*=...]`, because the substring
# form would also match `emojiEmojiItememojiItemDesc` — the label, not the item.
EMOJI_PANEL = (
    "div.componentsemojiemojiPanel, "
    '[class~="componentsemojiemojiPanel"], '
    "[class*='emojiPanel']"
)

# Class-only on purpose. `[data-apm-action="EmojiItem"]` sits on the *inner*
# image box, so listing it as an alternative would match every entry twice.
EMOJI_ITEM = 'div[class~="emojiEmojiItememojiItem"]'
EMOJI_ITEM_DESC = (
    'div[class~="emojiEmojiItememojiItemDesc"], '
    '[class~="emojiEmojiItememojiItemDesc"]'
)
EMOJI_ITEM_IMAGE = 'img[class~="commonMyImageimgReal"], [class*="emojiImgBox"] img'

# ==========================================================================
# Login
# ==========================================================================

# Positive markers for "signed in". The session cookie below is the reliable
# half; these are a fallback.
LOGGED_IN_HINT = (
    '[data-e2e="user-avatar"], '
    '[data-e2e="live-avatar"], '
    '[data-e2e="header-avatar"]'
)

# Cookie names Douyin sets after a successful login.
#
# These must be session cookies only. An earlier version also listed
# `passport_csrf_token` and `uid_tt`, and that was a real bug: Douyin sets those
# for anonymous visitors too, so the check reported "logged in" for a browser
# whose /chat was showing a login QR code. A positive signal is only useful if
# it cannot be produced by a logged-out visitor.
LOGGED_IN_COOKIES = (
    "sessionid",
    "sessionid_ss",
    "sid_tt",
)
