# staticwebapp.config.json — Azure SWA Routing Constraints

Azure Static Web Apps has strict wildcard rules for routes. All three must hold:

1. **Max one `*` per route** — `/a/*/b/*` is rejected
2. **`*` must be at the END of the path** — `/a/*/b` is rejected (mid-path wildcard)
3. **If anything follows `*`, it must be `.ext` only** — `*.txt` is OK, `*/page.txt` is rejected

Source: SWA CLI validation in `glob.ts` — the text after `*` is checked against
`/\.(\w+|\{\w+(,\w+)*\})$/` (a dot followed by a file extension or brace group).

## Consequences for `/models` routes

The frontend has two nested dynamic routes under `/models`:
- `/models/[id]/evaluate` → `out/models/_/evaluate.html`
- `/models/[id]/evaluations/[evalId]` → `out/models/_/evaluations/_.html`

We **cannot** route these individually because `/models/*/evaluate` puts the
wildcard mid-path (violates rule 2). Instead, `/models/*` is a single catch-all
that rewrites everything to the evaluations page HTML.

This means `/models/123/evaluate` gets the evaluations pre-rendered HTML, not
the evaluate HTML. This is fine because both are `'use client'` pages — they
render a loading spinner in the pre-rendered HTML and fetch all data client-side.
Next.js hydration corrects the page component almost immediately.

## Adding new routes

Routes with a single trailing wildcard work (`/section/*`). If you need a
new nested dynamic route like `/section/[a]/subsection/[b]`, you'll hit the
same constraint — use a `/section/*` catch-all and rely on client-side routing.
