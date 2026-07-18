"""Internet access: search, read pages, open sites."""

from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus

from .registry import registry


@registry.tool(
    "Search the web. Use for anything current: news, weather, facts you're unsure of, "
    "prices, sports scores. Returns titles, URLs and snippets.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> dict:
    from ddgs import DDGS

    results = DDGS().text(query, max_results=6)
    if not results:
        return {"ok": False, "error": "no results"}
    return {
        "ok": True,
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")[:300],
            }
            for r in results
        ],
    }


@registry.tool(
    "Fetch and read the text content of a web page URL. Use after web_search when a "
    "snippet isn't enough to answer.",
    {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full URL"}},
        "required": ["url"],
    },
)
def read_page(url: str) -> dict:
    import trafilatura

    html = trafilatura.fetch_url(url)
    if not html:
        return {"ok": False, "error": "couldn't fetch the page"}
    text = trafilatura.extract(html, include_comments=False) or ""
    if not text:
        return {"ok": False, "error": "page had no readable text"}
    return {"ok": True, "content": text[:4000]}


@registry.tool(
    "Open a website in the user's own default browser, hands-off — just showing "
    "them something. If YOU need to read, click or type on the site, use "
    "browser_open instead.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL or site name like 'github.com'"}
        },
        "required": ["url"],
    },
)
def open_website(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return {"ok": True, "message": f"opened {url}"}


@registry.tool(
    "Search YouTube and open the results, e.g. to play music or a video.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search on YouTube"}
        },
        "required": ["query"],
    },
)
def play_on_youtube(query: str) -> dict:
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    return {"ok": True, "message": f"opened YouTube results for '{query}'"}
