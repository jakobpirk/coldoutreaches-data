"""
crawl4ai bridge — render one or more URLs in a headless browser and print JSON
[{url, ok, html, mailto[]}]. Run with the isolated crawl venv (keeps crawl4ai's
deps off the system python that the rest of the pipeline uses):

    .venv-crawl/bin/python crawl_fetch.py <url> [url2 ...]

harvest_emails.py calls this so it can read JS-rendered / TLS-awkward pages that
plain `requests` misses, then runs its normal email extraction on the HTML.
"""
import sys, json, asyncio


async def crawl(urls):
    from crawl4ai import AsyncWebCrawler
    out = []
    async with AsyncWebCrawler(verbose=False) as crawler:
        for u in urls:
            try:
                r = await crawler.arun(url=u)
                links = r.links if isinstance(getattr(r, "links", None), dict) else {}
                mailto = []
                for grp in links.values():
                    for l in (grp or []):
                        href = str((l or {}).get("href", ""))
                        if href.lower().startswith("mailto:"):
                            mailto.append(href[7:])
                out.append({"url": u, "ok": bool(getattr(r, "success", False)),
                            "html": (getattr(r, "html", "") or "")[:300000],
                            "mailto": mailto})
            except Exception as e:
                out.append({"url": u, "ok": False, "error": str(e)[:200], "html": "", "mailto": []})
    return out


if __name__ == "__main__":
    urls = sys.argv[1:]
    try:
        res = asyncio.run(crawl(urls))
    except Exception as e:
        res = [{"url": u, "ok": False, "error": f"crawl bridge: {e}"[:200], "html": "", "mailto": []} for u in urls]
    print(json.dumps(res, ensure_ascii=False))
