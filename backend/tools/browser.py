"""Elara's own browser: a controlled Chromium she can actually drive.

Unlike open_website (fire-and-forget into the user's default browser), these
tools give her a headed Playwright browser she can navigate, read, click and
type in — the loop for "go to Amazon, compare monitors, tell me which".

Design notes:
- Async Playwright on the server's event loop. The sync API can't run there,
  and the to_thread pool would break Playwright's thread affinity.
- One persistent profile (cookies survive between tasks) in the data dir; the
  window is visible so the user watches her work.
- Ref scheme: browser_snapshot() stamps interactive elements with
  data-elara-ref="eN" and returns an outline; clicks/typing resolve that
  attribute. A ref that no longer matches means the page changed — the tool
  says "snapshot again" instead of guessing.
- Safety lives in browser_guard: credential/payment fields are hard-refused,
  purchase-shaped clicks need confirm=true.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from backend.paths import data_dir

from . import browser_guard
from .registry import registry

log = logging.getLogger("elara.browser")

PROFILE_DIR = data_dir() / "browser_profile"
MAX_SNAPSHOT_CHARS = 6000
MAX_READ_CHARS = 6000
MAX_ELEMENTS = 150

_pw = None
_context = None
_page = None
# serialize all page access — the model may emit several browser calls at once
_lock = asyncio.Lock()

# JS run in the page: tags visible interactive elements with data-elara-ref
# and returns one outline line per element.
_SNAPSHOT_JS = """
() => {
  document.querySelectorAll('[data-elara-ref]')
    .forEach(el => el.removeAttribute('data-elara-ref'));
  const sel = 'a[href], button, input, select, textarea, ' +
    '[role="button"], [role="link"], [role="combobox"], [role="checkbox"], ' +
    '[role="menuitem"], [role="tab"], [role="searchbox"], [contenteditable="true"]';
  const lines = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    n += 1;
    const ref = 'e' + n;
    el.setAttribute('data-elara-ref', ref);
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || tag;
    const label = (el.getAttribute('aria-label') || el.innerText || el.value ||
      el.getAttribute('placeholder') || el.getAttribute('title') || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 80);
    const extra = tag === 'input' ? ' type=' + (el.type || 'text') : '';
    lines.push('[' + ref + '] ' + role + extra + ' "' + label + '"');
    if (n >= %MAX%) break;
  }
  const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
    .map(h => h.innerText.trim().replace(/\\s+/g, ' ').slice(0, 100))
    .filter(Boolean).slice(0, 12);
  return {elements: lines.join('\\n'), headings};
}
""".replace("%MAX%", str(MAX_ELEMENTS))

_FIELD_ATTRS_JS = """
el => ({
  type: el.type || '',
  autocomplete: el.getAttribute('autocomplete') || '',
  name: el.getAttribute('name') || '',
  id: el.id || '',
  placeholder: el.getAttribute('placeholder') || '',
  label: el.getAttribute('aria-label') || '',
})
"""


def _install_chromium() -> None:
    """One-time browser download (~150 MB). Blocking; run off the loop."""
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        capture_output=True,
        timeout=600,
    )


async def _ensure_page():
    """The live page, launching a browser on first use.

    Prefers the machine's installed Chrome/Edge (channel launch): no separate
    download, and Chrome-for-Testing won't even start on boxes missing the
    VC++ runtime. Falls back to Playwright's bundled Chromium, downloading it
    if needed. The profile dir is Elara's own either way — her cookies never
    touch the user's real browser profile.
    """
    global _pw, _context, _page
    if _page is not None and not _page.is_closed():
        return _page

    from playwright.async_api import async_playwright

    if _pw is None:
        _pw = await async_playwright().start()

    def launch(channel: str | None):
        kwargs: dict = {
            "headless": False,
            "viewport": {"width": 1280, "height": 800},
        }
        if channel:
            kwargs["channel"] = channel
        return _pw.chromium.launch_persistent_context(str(PROFILE_DIR), **kwargs)

    last_exc: Exception | None = None
    for channel in ("chrome", "msedge", None):
        try:
            _context = await launch(channel)
            break
        except Exception as exc:
            last_exc = exc
            if channel is None and "Executable doesn't exist" in str(exc):
                ctx = registry.context()
                if ctx.speak:
                    await ctx.speak(
                        "One second — I need to download my browser first. "
                        "Only happens once."
                    )
                await asyncio.to_thread(_install_chromium)
                _context = await launch(None)
                break
            log.debug("browser channel %s unavailable: %s", channel, exc)
    else:
        raise RuntimeError(f"couldn't launch any browser: {last_exc}")

    _page = _context.pages[0] if _context.pages else await _context.new_page()
    return _page


def _no_browser() -> dict:
    return {"ok": False, "error": "no browser page open — call browser_open first"}


async def _snapshot(page) -> dict:
    data = await page.evaluate(_SNAPSHOT_JS)
    elements = data["elements"]
    if len(elements) > MAX_SNAPSHOT_CHARS:
        elements = elements[:MAX_SNAPSHOT_CHARS] + "\n…[truncated]"
    return {
        "ok": True,
        "url": page.url,
        "title": await page.title(),
        "headings": data["headings"],
        "elements": elements,
        "message": f"looking at {await page.title()}",
    }


async def _resolve(page, ref: str):
    """The tagged element for a ref, or None if the page moved on."""
    loc = page.locator(f'[data-elara-ref="{ref}"]')
    return loc.first if await loc.count() else None


@registry.tool(
    "Open a URL in YOUR controlled browser (the one you can click and type in) "
    "and return an outline of the page with clickable element refs. Use this — "
    "not open_website — whenever you need to interact with or read a site.",
    {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Address to open"}},
        "required": ["url"],
    },
    timeout=300.0,  # first call may download Chromium
)
async def browser_open(url: str) -> dict:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    async with _lock:
        page = await _ensure_page()
        await page.bring_to_front()
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(800)  # settle dynamic content a beat
        return await _snapshot(page)


@registry.tool(
    "Re-read the current browser page: outline with fresh element refs "
    "(e1, e2, …). Call after anything changes the page, or when a ref is stale.",
    timeout=60.0,
)
async def browser_snapshot() -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        return await _snapshot(_page)


@registry.tool(
    "Click an element in your browser by its ref from the last snapshot. For "
    "purchase/checkout buttons ask the user first, then retry with confirm=true.",
    {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Element ref, e.g. 'e12'"},
            "confirm": {
                "type": "boolean",
                "description": "true only after the user approved a purchase-like click",
            },
        },
        "required": ["ref"],
    },
    timeout=60.0,
)
async def browser_click(ref: str, confirm: bool = False) -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        el = await _resolve(_page, ref)
        if el is None:
            return {
                "ok": False,
                "error": f"ref '{ref}' is stale — the page changed. Call browser_snapshot again.",
            }
        try:
            label = (await el.inner_text(timeout=2_000)).strip()[:120]
        except Exception:
            label = ""
        risk = browser_guard.classify_click(label)
        if risk and not confirm:
            return {
                "ok": False,
                "needs_confirmation": True,
                "message": f"Clicking '{label}' {risk}. Ask the user to confirm, "
                "then retry with confirm=true.",
            }
        await el.click(timeout=10_000)
        await _page.wait_for_timeout(1_200)
        return await _snapshot(_page)


@registry.tool(
    "Type text into an input in your browser by its ref. Never used for "
    "passwords or payment details — those fields are refused; the user types "
    "them personally. Set submit=true to press Enter afterwards.",
    {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Element ref, e.g. 'e3'"},
            "text": {"type": "string", "description": "Text to type"},
            "submit": {"type": "boolean", "description": "Press Enter after typing"},
        },
        "required": ["ref", "text"],
    },
    timeout=60.0,
)
async def browser_type(ref: str, text: str, submit: bool = False) -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        el = await _resolve(_page, ref)
        if el is None:
            return {
                "ok": False,
                "error": f"ref '{ref}' is stale — the page changed. Call browser_snapshot again.",
            }
        attrs = await el.evaluate(_FIELD_ATTRS_JS)
        risk = browser_guard.classify_field(attrs)
        if risk:
            return {
                "ok": False,
                "error": f"that's {risk} — I never type those. Ask the user to "
                "enter it themselves, then continue.",
            }
        await el.fill(text, timeout=10_000)
        if submit:
            await el.press("Enter")
            await _page.wait_for_timeout(1_500)
            return await _snapshot(_page)
        return {"ok": True, "message": f"typed into {ref}"}


@registry.tool(
    "Scroll the browser page up or down one screen to reveal more content.",
    {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["down", "up"]},
        },
        "required": ["direction"],
    },
    timeout=30.0,
)
async def browser_scroll(direction: str) -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        sign = "-" if direction == "up" else ""
        await _page.evaluate(f"window.scrollBy(0, {sign}window.innerHeight * 0.8)")
        await _page.wait_for_timeout(500)
        return await _snapshot(_page)


@registry.tool("Go back one page in your browser.", timeout=30.0)
async def browser_back() -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        await _page.go_back(wait_until="domcontentloaded", timeout=20_000)
        await _page.wait_for_timeout(800)
        return await _snapshot(_page)


@registry.tool(
    "Read the current browser page as clean full text. Use after navigating "
    "somewhere whose content you need in detail, not just its outline.",
    timeout=60.0,
)
async def browser_read() -> dict:
    async with _lock:
        if _page is None or _page.is_closed():
            return _no_browser()
        html = await _page.content()
    import trafilatura

    text = await asyncio.to_thread(
        trafilatura.extract, html, url=_page.url, include_links=False
    )
    if not text:
        return {"ok": False, "error": "couldn't extract readable text from this page"}
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n…[truncated]"
    return {"ok": True, "url": _page.url, "text": text}


@registry.tool("Close your controlled browser window when the task is finished.")
async def browser_close() -> dict:
    global _pw, _context, _page
    async with _lock:
        if _context is None:
            return {"ok": True, "message": "browser wasn't open"}
        try:
            await _context.close()
        except Exception:
            log.debug("browser close raced", exc_info=True)
        try:
            if _pw is not None:
                await _pw.stop()
        except Exception:
            log.debug("playwright stop raced", exc_info=True)
        _pw = _context = _page = None
        return {"ok": True, "message": "browser closed"}
