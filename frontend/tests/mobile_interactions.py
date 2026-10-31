"""Touch smoke checks against the localhost seed account; never dispatches paid work."""

import asyncio, json, os
from playwright.async_api import async_playwright

OUT = os.environ.get("MOBILE_SCREENSHOTS", "/tmp/sightlab-mobile")
os.makedirs(OUT, exist_ok=True)


async def main():
    async with async_playwright() as p:
        b = await p.webkit.launch()
        c = await b.new_context(
            viewport={"width": 440, "height": 956},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        r = await c.request.post(
            "http://localhost:8000/api/auth/login",
            data={"email": "stuart.leal23@gmail.com", "password": "password"},
        )
        auth = await r.json()
        await c.add_init_script(
            'localStorage.setItem("access_token",'
            + json.dumps(auth["access_token"])
            + ");"
        )

        async def relay(route):
            url = route.request.url
            if "resolve=true" in url and os.environ.get("MOBILE_LEGACY_IMAGES") == "1":
                from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

                parts = urlsplit(url)
                params = dict(parse_qsl(parts.query))
                params.pop("resolve", None)
                params["token"] = auth["access_token"]
                file_url = urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, urlencode(params), "")
                )
                await route.fulfill(json={"url": file_url})
                return
            r = await route.fetch()
            await route.fulfill(
                response=r,
                headers={
                    **r.headers,
                    "access-control-allow-origin": "http://localhost:3005",
                    "access-control-allow-credentials": "true",
                },
            )

        await c.route("http://localhost:8000/**", relay)
        page = await c.new_page()
        await page.goto("http://localhost:3005/images")
        await page.wait_for_selector(".library-tile")
        await page.wait_for_timeout(1500)
        # Phone density is independent of device width.
        grid = (
            page.locator(".library-tile")
            .first.locator("..")
            .locator("..")
            .locator("..")
        )
        positions = await page.locator(".library-tile").evaluate_all(
            "(els)=>els.slice(0,5).map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))"
        )
        for density, count in [("S", 3), ("L", 1), ("M", 2)]:
            await (
                page.get_by_role("group", name="Thumbnail size")
                .get_by_role("button", name=density, exact=True)
                .tap()
            )
            await page.wait_for_timeout(200)
            assert (
                await grid.evaluate(
                    '(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length'
                )
                == count
            )
        before = await page.locator(".library-tile").evaluate_all(
            "(els)=>els.slice(0,8).map(e=>e.parentElement.parentElement.getBoundingClientRect().x)"
        )
        await page.locator("main").evaluate("(e)=>e.scrollTop=e.scrollHeight")
        await page.wait_for_timeout(1000)
        after = await page.locator(".library-tile").evaluate_all(
            "(els)=>els.slice(0,8).map(e=>e.parentElement.parentElement.getBoundingClientRect().x)"
        )
        assert before == after
        await page.locator("main").evaluate("(e)=>e.scrollTop=0")
        await page.get_by_role("button", name="Select", exact=True).first.tap()
        await page.locator(".library-tile").first.locator("button").first.tap()
        await page.get_by_role("button", name="More tools", exact=True).tap()
        await page.get_by_role("dialog", name="Inspector").wait_for()
        await page.screenshot(path=OUT + "/phone-selection-sheet.png")
        await page.get_by_role("button", name="Edit", exact=True).tap()
        assert (
            await page.get_by_role("dialog", name="Inspector")
            .locator("textarea")
            .count()
            == 1
        )
        await page.get_by_role("button", name="Close inspector", exact=True).tap()
        await page.get_by_role("button", name="Clear selection", exact=True).tap()
        await page.locator(".library-tile").first.locator("button").first.tap()
        await page.get_by_role("dialog", name="Image viewer").wait_for()
        await page.screenshot(path=OUT + "/phone-viewer.png")
        await page.get_by_role(
            "button", name="Details / Tags / Description", exact=True
        ).tap()
        await page.get_by_role("tab", name="Tags", exact=True).tap()
        await page.screenshot(path=OUT + "/phone-viewer-details.png")
        await page.get_by_role("button", name="Close details", exact=True).tap()
        viewer = page.get_by_role("dialog", name="Image viewer")
        await viewer.dispatch_event(
            "touchstart", {"touches": [{"clientX": 330, "clientY": 400}]}
        )
        await viewer.dispatch_event(
            "touchend", {"changedTouches": [{"clientX": 50, "clientY": 405}]}
        )
        await page.wait_for_timeout(300)
        await viewer.dispatch_event(
            "touchstart", {"touches": [{"clientX": 220, "clientY": 300}]}
        )
        await viewer.dispatch_event(
            "touchend", {"changedTouches": [{"clientX": 220, "clientY": 500}]}
        )
        await page.get_by_role("dialog", name="Image viewer").wait_for(state="detached")
        await page.get_by_role("button", name="More", exact=True).tap()
        await page.get_by_role("dialog", name="More", exact=True).wait_for()
        await page.screenshot(path=OUT + "/phone-more.png")
        await page.get_by_label("Theme", exact=True).select_option("dark")
        assert await page.locator("html").evaluate('(e)=>e.classList.contains("dark")')
        await page.get_by_role("button", name="Close More", exact=True).tap()
        for route in [
            "images",
            "models",
            "jobs",
            "billing",
            "settings",
            "admin",
            "debug",
        ]:
            await page.close()
            page = await c.new_page()
            await page.goto("http://localhost:3005/" + route)
            await page.wait_for_selector(".app-main")
            await page.wait_for_timeout(600)
            bad = await page.evaluate(
                """()=>[...document.querySelectorAll('button,a,select,input:not([type=checkbox]):not([type=radio])')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&r.top<innerHeight&&r.bottom>0&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none'&& (r.width<44||r.height<44)}).map(e=>({text:e.textContent.slice(0,50),cls:e.className,w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))"""
            )
            print(route, json.dumps(bad), flush=True)
            assert not bad, bad
        await b.close()


asyncio.run(main())
