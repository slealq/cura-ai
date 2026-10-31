"""Run with Python Playwright installed; frontend must run on localhost:3005.
Uses only the local seed admin. The relay works around local backend CORS;
legacy image resolution is adapted without changing backend configuration.
"""

import asyncio, json, os
from playwright.async_api import async_playwright

OUT = os.environ.get("MOBILE_SCREENSHOTS", "/tmp/sightlab-mobile")
os.makedirs(OUT, exist_ok=True)


async def main():
    async with async_playwright() as p:
        try:
            b = await p.webkit.launch()
            print("ENGINE webkit")
        except Exception:
            b = await p.chromium.launch()
            print("ENGINE chromium")
        request = await p.request.new_context()
        r = await request.post(
            "http://localhost:8000/api/auth/login",
            data={
                "email": "stuart.leal23@gmail.com",
                "password": os.environ.get("LOCAL_SEED_PASSWORD", "password"),
            },
        )
        auth = await r.json()
        for width, height in [(440, 956), (390, 844), (1440, 900), (1920, 1080)]:
            for theme in ["light", "dark"] if width < 768 else ["light"]:
                c = await b.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=3 if width < 768 else 1,
                    has_touch=width < 768,
                    is_mobile=width < 768,
                )
                await c.add_init_script(
                    'localStorage.setItem("access_token", '
                    + json.dumps(auth["access_token"])
                    + ');localStorage.setItem("theme",'
                    + json.dumps(theme)
                    + ");"
                )

                async def relay(route):
                    url = route.request.url
                    if (
                        "resolve=true" in url
                        and os.environ.get("MOBILE_LEGACY_IMAGES") == "1"
                    ):
                        from urllib.parse import (
                            urlsplit,
                            parse_qsl,
                            urlencode,
                            urlunsplit,
                        )

                        parts = urlsplit(url)
                        params = dict(parse_qsl(parts.query))
                        params.pop("resolve", None)
                        params["token"] = auth["access_token"]
                        file_url = urlunsplit(
                            (
                                parts.scheme,
                                parts.netloc,
                                parts.path,
                                urlencode(params),
                                "",
                            )
                        )
                        await route.fulfill(json={"url": file_url})
                        return
                    response = await route.fetch()
                    await route.fulfill(
                        response=response,
                        headers={
                            **response.headers,
                            "access-control-allow-origin": "http://localhost:3005",
                            "access-control-allow-credentials": "true",
                        },
                    )

                await c.route("http://localhost:8000/**", relay)
                page = await c.new_page()
                for route in [
                    "images",
                    "clusters",
                    "models",
                    "jobs",
                    "billing",
                    "settings",
                    "admin",
                    "debug",
                    "upload",
                    "search",
                    "generate?advanced=1",
                    "edit?advanced=1",
                    "vision?advanced=1",
                ]:
                    await page.close()
                    page = await c.new_page()
                    await page.goto(
                        "http://localhost:3005/" + route, wait_until="domcontentloaded"
                    )
                    await page.wait_for_selector(".app-main")
                    await page.wait_for_timeout(1600)
                    await page.wait_for_selector(".app-main")
                    info = await page.evaluate(
                        """() => ({width:innerWidth,doc:document.documentElement.scrollWidth, main:document.querySelector('main').scrollWidth})"""
                    )
                    assert info["doc"] <= width, info
                    assert info["main"] <= width, info
                    if width < 768:
                        assert await page.locator(
                            'aside[aria-label="Navigation"]'
                        ).is_hidden()
                        assert await page.locator(".mobile-tabs").is_visible()
                        assert (
                            await page.locator("main").evaluate(
                                "(e)=>parseFloat(getComputedStyle(e).paddingBottom)"
                            )
                            >= 100
                        )
                        assert (
                            await page.locator(
                                'meta[name="viewport"][content*="viewport-fit=cover"]'
                            ).count()
                            >= 1
                        )
                    print(width, theme, route, json.dumps(info), flush=True)
                    await page.screenshot(
                        path=f"{OUT}/{'phone' if width < 768 else 'desktop'}-{width}-{theme}-{route.split('?')[0]}.png"
                    )
                await c.close()
        await b.close()


asyncio.run(main())
