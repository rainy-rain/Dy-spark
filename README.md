# DY-spark

Send one message a day to the friends you care about, so your Douyin chat
streaks stay alive — from the command line, on your own machine, with your own
account.

```
python -m dspark login        # scan the QR code once
python -m dspark scan         # list every chat and whether it has a spark
python -m dspark send         # dry run: lists who it would message
python -m dspark send --yes   # actually send
```

Repair tools, for when Douyin changes something:

```
python -m dspark edge         # open a browser with the debugging port on
python -m dspark pick         # click a page element, get its selector
python -m dspark probe        # dump the whole page
python -m dspark analyze      # work out selectors from a dump, offline
```

---

## Read this before anything else

Douyin requires an account to see the chat page, so this was built from material
that actually came off the live site, and the confidence varies by part:

| Part | Status |
|---|---|
| Browser layer: launch, session cookies, `storageState`, screenshots | **Verified** against live douyin.com |
| Login detection (logged in vs out) | **Verified** — correctly reports "logged out" |
| Home page hooks: message entry, login button | **Verified** |
| Chat rows and the spark badge | **Verified** — markup copied from DevTools, see below |
| The composer (Slate editor) | **Verified** — markup copied from DevTools, see below |
| Config loading and validation, error messages | **Verified** — every failure path tested |
| Dry-run, rate limiting, the two switches, variant filter | **Verified** — 82 offline tests |

Every selector now comes from markup that was actually read off the live site.
What remains untested is only the *interaction*: whether Slate accepts the
synthetic key events. `_send_to` therefore verifies the text landed before
pressing Enter, and says so plainly if it did not, rather than reporting a
message it never sent.

**Douyin's terms of service** do not invite automation. This tool only ever
messages people *you* are already talking to, from *your* account, and it
deliberately stays slow — but a streak is worth less than an account. Run `scan`
and `send` (dry run) for a few days before you trust it.

### What the real markup looks like

Chat row, copied from DevTools on a logged-in `douyin.com/chat`:

```html
<div data-e2e="conversation-item" class="conversationConversationItemWrapper">
  <div class="conversationConversationItemrowArea1">
    <div class="commonIMAvataravatarContainer">
      <span class="semi-avatar semi-avatar-circle ...">
        <img src="https://p26.douyinpic.com/img/aweme-avatar/...">
      </span>
    </div>
  </div>
  <div class="conversationConversationItemrowArea2">
    <div class="conversationConversationItemtitle">张三</div>
    <div class="commonStreakstreakContainer">
      <img class="commonStreakicon"
           src=".../flame_icon/normal/gray_normal.png" alt="">
      <div class="commonStreaknormalText"> 129 </div>
    </div>
  </div>
</div>
```

Three things worth taking from this:

1. **Conversation rows carry `data-e2e="conversation-item"`.** That is the row
   selector, and it is stable.
2. **The streak length is in the markup** (`commonStreaknormalText` → `129`).
   `scan` prints it, which turns "did detection work?" into something you can
   check by eye instead of trusting a yes/no flag.
3. **A grey flame sat on a 129-day streak.** This is the trap: grey is a normal
   list appearance, *not* an absent streak. All three known flame assets
   (`normal_normal`, `blue_normal`, `gray_normal`) therefore count by default,
   and `sending.spark_variants` lets you narrow that if you disagree.
4. **The list is virtualised.** `/chat` keeps roughly one screenful of rows in
   the DOM and recycles them as you scroll. Reading it once returns a window
   onto the list, not the list — the first working version found 13
   conversations and reported it with complete confidence. `scan` scrolls to the
   bottom instead, collecting as it goes and de-duplicating by avatar URL (a row
   index stops meaning anything once nodes have been recycled). On the machine
   this was built against, that took the count from 13 to 42.

   The scroll is done in JavaScript rather than with
   `locator.scroll_into_view_if_needed()`, because that waits for an element to
   be "stable" — and in a virtualised list the element being scrolled is exactly
   the one that keeps getting recycled. It failed mid-scroll, which silently
   truncated the results.
5. **Sending has its own version of the same problem.** The scan leaves the list
   scrolled to the bottom, and finding a specific friend only walks *downward* —
   so the first real run reported `Could not find '某位好友' in the list` for all
   nine friends near the top. The search now rewinds before every sweep, and
   sweeps twice: one sweep found 26 of 29 on one run and 29 of 29 on the next
   with no code change between them, and in this loop a flake is a friend whose
   streak breaks.
6. **Scroll by half a screen, not most of one.** The virtualiser can render
   fewer rows than fit on screen, so a 0.85-screen jump steps over a whole band
   of conversations. That is how a friend who was plainly in the list got
   reported as missing.

The composer, likewise copied from DevTools:

```html
<div data-e2e="msg-input" class="messageMsgInputcontainer">
  <div class="messageMsgInputinputRow">
    <div class="zone-container editor-kit-container messageEditorinputArea ..."
         data-slate-editor="true"
         contenteditable="true"
         data-placeholder="发送消息">
      <div class="ace-line" data-node="true" dir="auto">
        <span data-leaf="true">&#8203;</span>
      </div>
    </div>
  </div>
</div>
```

**It is a Slate.js editor, not a textarea.** Three consequences, all handled:

| Consequence | What the code does |
|---|---|
| `fill()` does nothing to a Slate editor | clicks to focus, then sends real key events |
| An empty composer still holds a zero-width space (U+200B) | `_COMPOSER_JS` strips `[\u200b-\u200d\ufeff]` before testing emptiness |
| Slate *might* refuse synthetic input | `_send_to` reads the composer back and refuses to press Enter if the text never arrived |

That second one is a genuine bug that would have shipped: JS's `String.trim()`
does not remove U+200B, so every successful send would have been misread as a
failure and followed by a pointless click on the fallback send button. A guard
test now pins the escaping, because a single missing backslash turns
`[\u200b-…]` into `[u200b-…]` — which matches the literal letters u, 2, 0, b.

Also read off the live site, for the login flow:

```html
<!-- The message entry is the 消息 button in the top bar -->
<div data-e2e="im-entry">
  <div><div data-e2e="something-button">
    <div><i></i></div><p>消息</p>
  </div></div>
</div>

<!-- The login button's class is hashed, so text is the only hook -->
<p class="VQdYTqcZ">登录</p>
```

Searching the DOM for `class~="login"` or `class~="avatar"` matches **nothing** —
yet `commonStreakicon` is a perfectly readable class. That is the lesson: Douyin
runs two naming systems at once. Layout uses hashed CSS-module names that change
every deploy; feature-level pieces keep readable names that do not. So prefer
`data-e2e`, then a *readable* class, and never a hash.

Two gotchas this surfaced, both now handled in code:

1. **Clicking the message entry while logged out does not raise an error.**
   Douyin silently bounces you to the featured feed (`/jingxuan`). Trusting the
   click would leave the tool reading an empty list and blaming its selectors,
   so `_goto_messages()` confirms arrival and tells you which of the two causes
   it is.
2. The message page failed to appear on the first attempt, and the tool says so
   explicitly rather than reporting "0 conversations found".

---

## How it works

### 1. Login lives in a JSON file, not in this code

The session is persisted with Playwright's own `storageState`, which serialises
cookies and localStorage to disk. This is the same approach the reference
project [laizan](https://github.com/GHkmmm/laizan) takes — its `ipc/auth.ts` is
about twenty lines and the whole of it is:

```ts
ipcMain.handle('hasAuth', () => Boolean(storage.get(StorageKey.auth)))
ipcMain.handle('login', async () => { await loginAndStorageState() })
```

So: the browser opens once, **you** scan the QR code, the state is written to
`.session/storage_state.json`, and every later run injects it. This tool never
sees a password, a verification code, or your phone.

### 2. Elements are found by `data-e2e`, not by class name

Douyin's class names are hashed and change on every deploy, so they are useless
as hooks. The attribute they do keep is `data-e2e`. laizan leans on it too — it
closes the comment panel with

```
[data-e2e="feed-active-video"] [data-e2e="feed-comment-icon"]
```

and triggers a like by pressing `z` rather than clicking anything. Stable
attributes plus keyboard shortcuts is the whole trick.

### 3. Nothing is sent unless two switches agree

`sending.enabled: true` in the config means "this tool is allowed to send at
all". The `--yes` flag means "send on this run". Both are required. A run
without `--yes` prints exactly who it would message and with what, then stops.

---

## Install

Requires Python 3.10 or newer.

```bash
cd DY-spark

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Then install Chromium **into the project** rather than your per-user cache, so
the whole tool stays self-contained:

```bash
# Windows (PowerShell)
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.browsers"
python -m playwright install chromium

# macOS / Linux
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" python -m playwright install chromium
```

That is a one-time ~700 MB download into `DY-spark/.browsers/` (it is
gitignored). You only need the environment variable for the *install* —
`dspark/browser.py` finds `.browsers/` at runtime by itself, so you never have
to export anything again.

Finally:

```bash
cp config.example.yaml config.yaml     # Windows: copy config.example.yaml config.yaml
```

---

## Quick start

### Step 1 — log in

```bash
python -m dspark login
```

A real browser window opens. Scan the QR code with the Douyin app. The window
closes itself once the session is saved.

Check it worked:

```bash
python -m dspark status
```

### Step 2 — scan, and check the spark detection

```bash
python -m dspark scan
```

Sends nothing. It walks the chat list and prints one line per conversation:

```
  #  spark   days  variant             name
---  -----  -----  ------------------  -----
  1  yes      129  gray_normal.png     张三
  2  yes       12  normal_normal.png   张三
  3  -          -  -                   王五
  4  yes        3  blue_normal.png     赵六

[ok] 24 conversation(s), 11 with a spark
[i] strategy `spark` would message exactly those 11.
[i] Nothing was sent.
```

**Read that table before going any further.** Compare a few rows with what the
Douyin app shows you: if the day counts match and the right people are marked
`yes`, detection is right. If not, go to Step 3.

The `variant` column is the filename of the flame image that was found. To skip
a particular colour, list the ones to keep under `sending.spark_variants`.

### Step 3 — fix the selectors (only if Step 2 looked wrong)

Two ways, and the first one is much faster.

**(a) `pick` — click the element, get the selector.** Recommended:

```bash
python -m dspark pick
```

A browser opens with a blue badge in the top-left corner. Log in, walk to the
message page, then click the badge to turn picking on. Now every element you
click prints its selectors in the terminal, best first:

```
[ok] <textarea>  
[i]   textarea[placeholder="发送消息"] <- best
[i]   div[contenteditable="true"]
```

It never suggests a hashed class name. The candidates it offers, in order of how
long they usually survive:

| Order | What | Why |
|---|---|---|
| 1 | `[data-e2e="..."]` | the attribute Douyin actually maintains |
| 2 | an ancestor's `data-e2e` + tag | for icons and inner spans |
| 3 | `#id`, `placeholder`, `aria-label`, `role` | stable when present |
| 4 | other `data-*` attributes | often generated, but usually stable |
| 5 | `tag:has-text("...")` | short visible text |

It survives navigation, because it is installed as an init script rather than
once on a page — so you can log in and walk around before picking anything.
Results are also saved to `diagnostics/picked-<time>.json`.

**(b) `probe` — dump everything.** Use this when you need to see the whole page:

```bash
python -m dspark probe
```

This writes three files into `diagnostics/`:

| File | What it is |
|---|---|
| `probe-<time>.png` | a screenshot — often enough on its own |
| `probe-<time>.html` | the full DOM, for searching |
| `probe-<time>.json` | every `data-e2e` value on the page |

Then edit `dspark/selectors.py` — the constants under *Message page* are the
ones marked unverified. Run `pick` or `probe` again until the counts look right.

> If you cannot find a streak badge at all, Douyin's web client may not render
> one. In that case set `sending.strategy: list` and name your friends under
> `sending.targets` — the tool then never needs to read the badge.

### Step 4 — dry run

```bash
python -m dspark send
```

Prints who it *would* message and with what. Nothing is sent. Repeat until the
list is exactly the people you expect.

### Step 5 — enable and send

In `config.yaml`:

```yaml
sending:
  enabled: true
```

Then:

```bash
python -m dspark send --yes
```

Keep `browser.headless: false` for the first real run, so you can watch it.

---

## Configuration

| Key | Meaning |
|---|---|
| `session_file` | where the login is saved. Delete it to force a new QR login. |
| `browser.headless` | `false` shows the window. Keep it visible while tuning. |
| `browser.typing_delay_ms` | random per-keystroke delay `[min, max]` |
| `browser.slow_mo_ms` | slows every Playwright action down |
| `douyin.navigate_via_home` | `true` clicks into messages; `false` goes straight to `messages_url` |
| `sending.enabled` | master switch for sending |
| `sending.strategy` | `spark` (only streaks) · `list` (only `targets`) · `all` (everyone) |
| `sending.spark_variants` | which flame assets count; empty = all three |
| `sending.targets` | friend names, used by the `list` strategy |
| `sending.messages` | one is picked at random per friend |
| `sending.delay_between_ms` | random gap between two friends `[min, max]` |
| `sending.max_per_run` | hard ceiling, whatever the strategy picked |
| `logging.verbose` | print every page action |

Run `python -m dspark config` to see what the file actually resolves to.

---

## Running it daily

**Windows — Task Scheduler.** Create a Basic Task, daily, action *Start a
program*:

- Program: `C:\path\to\DY-spark\.venv\Scripts\python.exe`
- Arguments: `-m dspark send --yes`
- Start in: `C:\path\to\DY-spark`

**macOS / Linux — cron:**

```
0 21 * * * cd /path/to/DY-spark && .venv/bin/python -m dspark send --yes
```

Either way, set `logging.save_to_file: true` so there is a record in
`diagnostics/dspark-YYYYMMDD.log` of what ran and what it did.

The streak only needs one message per day, so once a day is enough — running it
more often just makes you look automated.

---

## Project layout

```
DY-spark/
├── config.example.yaml     template; copy to config.yaml
├── requirements.txt
├── dspark/
│   ├── __main__.py         CLI entry point        (python -m dspark)
│   ├── config.py           loading + validation
│   ├── browser.py          Playwright session, storageState, human-ish typing
│   ├── selectors.py        ALL Douyin selectors — the file to fix
│   ├── picker.py           interactive "click an element, get its selector"
│   ├── streak.py           login / status / probe / send
│   └── console.py          output, mirrored to a log file
├── tests/                  offline unit tests (no browser, no network)
├── .session/               your login (gitignored)
├── .browsers/              the Chromium copy (gitignored)
└── diagnostics/            probe dumps, picked selectors, logs (gitignored)
```

## Tests

The parts that decide *who gets a message* are covered by offline tests:

```bash
python -m unittest discover -s tests -t . -v
```

19 tests: config defaults, every validation failure path, and all three target
strategies including the per-run cap. No browser and no network needed.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `config file not found` | `cp config.example.yaml config.yaml` |
| `Playwright is not installed` | `pip install -r requirements.txt` then `python -m playwright install chromium` |
| `Could not attach to the browser at http://127.0.0.1:9222` | Nothing is listening on the port. Run `python -m dspark edge` first. It opens its **own** browser profile, so any Edge or Chrome you already have open is left alone — no need to close anything. |
| `Not logged in`, on a browser that looks signed in | The dspark profile is a separate browser profile from your everyday one, so it needs its own single sign-in. Do it in the window `dspark edge` opened. |
| `status` says the session expired | Douyin logs sessions out. `python -m dspark login` again. |
| `Conversations found: 0` | `CONVERSATION_ITEM` is stale. Run `probe` and compare. |
| The scan finds far fewer conversations than you have | The list is virtualised and the scroll may be stopping early. Run with `-v` and check the `rewound`/`scroll` lines. |
| `Could not find 'X' in the list` | The search could not reach that row. Run with `-v` to see the sweep range; the search rewinds and sweeps twice, so a persistent miss means the row is not in the list it is scanning. |
| It messages the wrong person | `CONVERSATION_ITEM` is matching too broadly. Tighten it using `probe` output. |
| Nothing gets sent, no error | The composer selector is wrong, or the page needs the send button rather than Enter. Check with `-v`. |
| Worked for a week, then stopped | Douyin shipped a redesign. `probe` again; it is a selector fix, not a rewrite. |

Add `-v` to any command to watch every page action:

```bash
python -m dspark send -v
```

---

## Reference

The `data-e2e` approach, the `storageState` login, and the keyboard-shortcut
technique (`z` to like, `ArrowDown` for the next video, `x` to close a panel)
all come from reading [laizan](https://github.com/GHkmmm/laizan), a
Playwright-based Douyin tool. Its `src/main/elements/douyin.ts` is worth
skimming if you plan to extend this.
