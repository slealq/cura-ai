Run the frontend with `NEXT_PUBLIC_API_URL=http://localhost:8000 npx next dev -p 3005`.
With Python Playwright installed, run:

```sh
playwright install webkit
python frontend/tests/mobile_smoke.py
python frontend/tests/mobile_interactions.py
```

Screenshots default to `/tmp/sightlab-mobile`; set `MOBILE_SCREENSHOTS` to override.
The tests authenticate only against the local seed account. `LOCAL_SEED_PASSWORD`
overrides its documented password. They never submit generation, training, billing,
or destructive operations.

The route sweep covers 440×956 and 390×844 at DPR 3 in both themes, plus 1440×900
and 1920×1080 desktop screenshots. It asserts document and content overflow,
mobile navigation visibility, content clearance, and viewport metadata. Touch
checks cover density, append-only column assignments, selection tools, viewer
swipes/details, theme changes, and visible control dimensions.

The response relay preserves real localhost API data while bypassing the local
backend's port-3005 CORS restriction (GitHub #72). If the running Docker backend
predates authenticated image URL resolution, set `MOBILE_LEGACY_IMAGES=1` to adapt
its file URLs in the test harness. No backend or database configuration is changed.
