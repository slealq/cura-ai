Verified 2026-10-31 against the local Docker backend, using the seed admin only.
Baseline: `baafbd2` (before this branch's changes).

- Playwright WebKit 26, touch enabled, DPR 3: 440×956 and 390×844, light and dark.
- All 13 main authenticated routes passed document and main-content overflow
  assertions: Library, Clusters, Models, Jobs, Billing, Settings, Admin, Debug,
  Upload, Search, advanced Create, Edit, and Vision. Folder detail also passed
  at both phone sizes and themes. There were no clusters in the local fixture
  to exercise an existing cluster detail.
- S/M/L produce 3/2/1 phone columns. Existing column assignments survive append.
  Select mode, selection tools, Edit handoff, viewer swipe navigation/dismissal,
  image information tabs, More, theme switching, and visible 44px controls passed.
- Model and Job inspectors, training modal sizing, and all six Admin tabs passed.
- 1440×900 and 1920×1080 desktop screenshots captured. Six 1440px route screenshots
  (Library, Models, Jobs, Billing, Settings, Admin) matched the original commit
  exactly after masking only the animated logo at (12,12)–(44,44).
- Phone content reserves 150px plus the bottom safe-area inset for navigation
  and selection actions. Viewport-fit and Apple home-screen metadata are present.

Screenshots: `/private/tmp/claude-501/-Users-stuartleal-src-cura-ai/c378364d-9de1-4a10-890f-9d60018f2ec0/scratchpad/mobile/`.

The tests relayed real localhost responses around the port-3005 CORS restriction
(#72) and adapted the older Docker backend's image-resolution contract. No backend,
Azure, or database settings were changed. Paid, destructive, and background job
submission were intentionally not exercised. Physical iPhone/browser chrome,
keyboard, and home-screen installation still need a real-device check.
