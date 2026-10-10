"""Interactive selector picker.

The message page cannot be inspected without an account, and guessing at
selectors from a screenshot is slow and error-prone. So instead of guessing:
click the element you want, and this reports a selector you can paste straight
into `selectors.py`.

It never suggests a hashed class name. Douyin's classes look like `VQdYTqcZ`
and change on every deploy; anything built on them breaks within a week. The
candidates it does offer, in order of how long they tend to survive, are:

    1. [data-e2e="..."]                    the attribute Douyin actually keeps
    2. an ancestor's data-e2e plus a tag
    3. #id, placeholder, aria-label, role  (stable when present)
    4. other data-* attributes
    5. tag:has-text("...")                 short visible text

The picker survives page navigation, because it is installed as an init script
rather than once on a single page. That matters: you will need to log in and
walk to the message list before there is anything worth picking.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import console
from .browser import open_session, use_local_browsers
from .config import Config

DIAGNOSTICS_DIR = Path("diagnostics")

# Runs before any page script, on every navigation and in every frame, so the
# badge is there whenever you need it.
PICKER_JS = r"""
(() => {
  if (window.__dsparkPickerInstalled) return;
  window.__dsparkPickerInstalled = true;

  var picking = false;
  var lastHover = null;
  var HL = '2px solid #4f9cf9';

  function makeBadge() {
    if (document.getElementById('__dspark_badge')) return;
    if (!document.documentElement) return;

    var el = document.createElement('div');
    el.id = '__dspark_badge';
    el.textContent = 'dspark picker: OFF';
    el.style.cssText = [
      'position:fixed', 'top:10px', 'left:10px', 'z-index:2147483647',
      'padding:6px 12px', 'border-radius:6px', 'cursor:pointer',
      'font:600 12px/1.4 -apple-system,Segoe UI,Microsoft YaHei,sans-serif',
      'background:#4f9cf9', 'color:#06121f',
      'box-shadow:0 2px 12px rgba(0,0,0,.45)', 'user-select:none'
    ].join(';');

    el.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      picking = !picking;
      el.textContent = 'dspark picker: ' + (picking ? 'ON' : 'OFF');
      el.style.background = picking ? '#2ecc71' : '#4f9cf9';
      if (!picking && lastHover && lastHover.style) {
        lastHover.style.outline = '';
        lastHover = null;
      }
    }, true);

    document.documentElement.appendChild(el);
  }

  function describe(el) {
    var tag = (el.tagName || '?').toLowerCase();
    var out = {
      tag: tag,
      text: String(el.innerText || el.value || '').trim().slice(0, 60),
      candidates: []
    };
    var c = out.candidates;
    var a, i, at;

    var own = el.getAttribute && el.getAttribute('data-e2e');
    if (own) c.push('[data-e2e="' + own + '"]');

    var p = el.parentElement, hops = 0;
    while (p && hops < 6) {
      if (p.getAttribute) {
        a = p.getAttribute('data-e2e');
        if (a) { c.push('[data-e2e="' + a + '"] ' + tag); break; }
      }
      p = p.parentElement;
      hops++;
    }

    if (el.id && !/^[0-9]/.test(el.id) && el.id.indexOf('__dspark') !== 0) {
      c.push('#' + el.id);
    }

    if (el.getAttribute) {
      a = el.getAttribute('placeholder');
      if (a) c.push(tag + '[placeholder="' + a + '"]');

      a = el.getAttribute('aria-label');
      if (a) c.push('[aria-label="' + a + '"]');

      a = el.getAttribute('role');
      if (a) c.push(tag + '[role="' + a + '"]');

      if (el.getAttribute('contenteditable') === 'true') {
        c.push(tag + '[contenteditable="true"]');
      }
    }

    if (tag === 'textarea') c.push('textarea');
    if (tag === 'input') c.push('input[type="' + (el.type || 'text') + '"]');

    if (el.attributes) {
      for (i = 0; i < el.attributes.length; i++) {
        at = el.attributes[i];
        if (at.name.indexOf('data-') === 0 && at.name !== 'data-e2e'
            && at.value && at.value.length < 40) {
          c.push(tag + '[' + at.name + '="' + at.value + '"]');
        }
      }
    }

    var t = String(el.innerText || '').trim();
    if (t && t.length <= 14 && t.indexOf('\n') === -1) {
      c.push(tag + ':has-text("' + t + '")');
    }

    return out;
  }

  document.addEventListener('mouseover', function (e) {
    if (!picking) return;
    if (lastHover && lastHover.style) lastHover.style.outline = '';
    lastHover = e.target;
    if (lastHover && lastHover.style) lastHover.style.outline = HL;
  }, true);

  document.addEventListener('click', function (e) {
    if (!picking) return;
    if (e.target && e.target.id === '__dspark_badge') return;
    e.preventDefault();
    e.stopPropagation();
    if (e.target && e.target.style) e.target.style.outline = '';
    lastHover = null;
    try { window.__dsparkPick(describe(e.target)); } catch (err) {}
  }, true);

  makeBadge();
  document.addEventListener('DOMContentLoaded', makeBadge);
})();
"""


def _format_report(payload: dict[str, Any]) -> None:
    tag = payload.get("tag", "?")
    text = (payload.get("text") or "").replace("\n", " ")
    candidates = payload.get("candidates") or []

    console.ok(f"<{tag}>  {text[:40]}")
    if not candidates:
        console.warn("  no stable selector found for this element")
        return
    for index, candidate in enumerate(candidates, start=1):
        marker = " <- best" if index == 1 else ""
        console.info(f"  {candidate}{marker}")


async def run(cfg: Config) -> int:
    console.step("Selector picker")

    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []

    console.info("A browser window is opening.")
    console.info("")
    console.info("  1. Log in if you need to, and walk to the page you care about.")
    console.info("  2. Click the blue badge in the top-left corner to turn picking ON.")
    console.info("  3. Click any element - its selectors print here.")
    console.info("     The first one is the most stable; that is the one to use.")
    console.info("  4. Close the browser window when you are done.")
    console.info("")

    def on_pick(_source: Any, payload: dict[str, Any]) -> None:
        collected.append(payload)
        _format_report(payload)

    async with open_session(cfg, headless=False) as session:
        # The binding and the init script both live on the context, so they
        # survive navigation and reach every frame.
        await session.context.expose_binding("__dsparkPick", on_pick)
        await session.context.add_init_script(PICKER_JS)

        page = session.page
        await page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")

        console.info("Waiting for you. Ctrl+C here also works.")
        try:
            # The page is closed by the user; poll until it is gone.
            while True:
                if page.is_closed():
                    break
                await page.wait_for_timeout(500)
        except Exception:
            pass

    if collected:
        out = DIAGNOSTICS_DIR / f"picked-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.write_text(
            json.dumps(collected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.step("Summary")
        console.ok(f"{len(collected)} element(s) picked")
        console.info(f"Saved to {out}")
        console.info("")
        console.info("Paste the FIRST candidate of each into dspark/selectors.py:")
        for payload in collected:
            candidates = payload.get("candidates") or []
            best = candidates[0] if candidates else "(none)"
            label = (payload.get("text") or "").replace("\n", " ")[:26]
            console.info(f"  {payload.get('tag','?'):<8} {label:<28} {best}")
    else:
        console.warn("Nothing was picked.")

    return 0
