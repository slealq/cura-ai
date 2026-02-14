# staticwebapp.config.json — Route Ordering

Azure Static Web Apps allows **at most one `*` wildcard per route**, and routes
are matched **top-to-bottom (first match wins)**.

The `/models` routes are ordered carefully to work around this limitation:

```
/models/*/evaluate.txt   →  matches /models/123/evaluate.txt
/models/*/evaluate       →  matches /models/123/evaluate
/models/*.txt            →  catch-all for /models/123/evaluations/456.txt
/models/*                →  catch-all for /models/123/evaluations/456
```

The evaluate routes (single path segment after the wildcard) come **before** the
broad catch-alls. Since `*` matches across path segments (including `/`), the
catch-alls at the bottom handle the two-segment evaluations paths without needing
a second wildcard.

If you add new nested routes under `/models/`, place more-specific patterns
**above** the catch-alls to avoid them being swallowed.
