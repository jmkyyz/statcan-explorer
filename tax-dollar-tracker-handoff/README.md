# Tax Dollar Tracker — handoff

An interactive calculator. A reader enters an annual income and picks a province
or territory; the tool estimates their federal and provincial income tax and
shows how those dollars are distributed across 22 categories of government
spending.

Contact: Jason Kirby.

---

## Status: the numbers are not final

The tool is going through an accuracy review with outside accountants. Please
treat this as a build for **evaluating hosting**, not as publish-ready content.
Nothing here should go live before that review is back and its findings are
folded in.

Everything in the *Integration* section below can be settled in parallel — the
technical shape of the page won't change when the numbers do.

---

## What you are getting

```
tax-dollar-tracker.html      the whole application, one file
provincial-data-sources.md   research behind the provincial spending split
README.md                    this file
```

That is genuinely the whole thing. There is no repository to clone, no
package.json, no pipeline.

## Dependencies: none

This matters more than it sounds, so to be explicit:

- **No external requests at runtime.** Zero. Open the network tab and you will
  see exactly one request: the HTML document itself.
- **No CDN.** Chart.js v4.4.1 (MIT) is inlined directly into the file. There is
  no third-party host to allowlist, so there is nothing here for a
  Content-Security-Policy to block.
- **No backend, no API, no database.** Every number — tax brackets, spending
  shares — is a literal baked into the page. All arithmetic runs client-side.
- **No build step.** No transpiling, no bundling. The file in your hands is the
  file that ships.
- **No fonts, images, iframes, cookies, `localStorage`, analytics, or service
  worker.**

It is a static asset. Drop it on any web server and it works. It also works
opened straight from disk with no server at all, which makes review easy.

The four `https://` links in the page are citations in the Sources & Notes
section — links a reader clicks, not resources the page loads.

Earlier drafts *did* pull Chart.js from `cdn.jsdelivr.net`. That has been
removed. If you ever see a jsdelivr request from this page, you have an old
copy — please come back for the current one.

**Page weight:** 252KB uncompressed, 83KB gzipped, ~205KB of which is the
charting library. One request, no round-trips, no render-blocking fetch.

## Analytics

There are no analytics hooks of any kind. If you need them, they need adding —
tell me the snippet and I will fold it in, or add it yourself.

## Metadata

The page sets `<title>` and a viewport meta tag, and nothing else. No
description, no Open Graph or Twitter card tags, no canonical URL. If your CMS
supplies those, great. If this is hosted as a standalone page, someone needs to
write them.

---

## Integration: the one decision I need from you

The file is a complete HTML document with its own `<head>`. How you want to host
it changes what work is needed, and I would rather ask than guess:

**Option A — standalone page.** Serve the file as-is at its own URL. Zero work.

**Option B — iframe embed inside an article.** Also zero work. Needs a sensible
height; the page is responsive with breakpoints at 980px and 600px, and the
chart grows with the number of categories, so a fixed height will either clip or
leave a gap. Height-messaging via `postMessage` is the usual fix and I am happy
to add it.

**Option C — inline into a Globe template.** This one needs work first, and it
is worth flagging clearly. The stylesheet opens with a global reset:

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
```

Dropped into a host page as-is, that applies to *every element on the page*, not
just the tracker — it will strip margins and padding off your surrounding
article furniture. All the styling would need scoping under a wrapper class
first. Very doable, just not free, and not something to discover in staging.

If in doubt, B is the low-risk default.

## Accessibility

Not formally audited. The controls are native `<input type="number">` and
`<select>` elements with real labels, so keyboard and screen-reader basics
should hold up, and results are real DOM text rather than image content. The
chart is a `<canvas>`, which is opaque to screen readers — but every value in it
is also rendered in the breakdown table immediately below, so no information is
chart-only. Worth a proper pass before publication.

---

## Where the numbers come from

**Tax brackets (2025)** — Canada Revenue Agency, all 13 jurisdictions. Applies
the basic personal amount, the Ontario surtax, the Ontario Health Premium, and
the Quebec federal abatement.

**Federal spending** — Public Accounts of Canada 2025, Volume I, Section 3
(Expenses), fiscal year 2024–25. Actual spending, not budget projections,
against total expenses of $543.3-billion.

One deliberate departure: Veterans Affairs. In the Public Accounts, veterans'
disability and future benefits are booked as personnel expenses government-wide,
which leaves the department's own ministry segment at just $546-million — wildly
understating it. The tracker uses the $7.2-billion of total expenses from
Veterans Affairs' own audited departmental financial statements instead.

**Provincial spending** — Statistics Canada Table 10-10-0005-01, CCOFOG by
consolidated government component, reference year 2024, consolidated
provincial-territorial-and-local series. Note that this universe consolidates
municipalities, school boards, hospitals and universities into provincial
spending — which is why the column is not labelled simply "provincial."

Full reasoning, including the alternatives rejected and why, is in
`provincial-data-sources.md`.

## Scope, and what it deliberately excludes

Federal and provincial **income tax only**. It does not include CPP or EI
contributions, GST/HST, property tax, or fuel and carbon charges — so it is not
the full gap between gross pay and take-home. CPP and EI are excluded on purpose:
they are contributions toward benefits you may later receive, not taxes.

The tool applies the basic personal amount and nothing else — no employment
credits, no provincial low-income reductions. **This makes the tax figure run
high**, by a few per cent at upper incomes and by considerably more at low ones.
The page says so prominently. It does not distort the spending breakdown, since
those credits scale the whole bill rather than moving money between categories.

## Keeping it current

Two independent refresh cycles:

- **Each November**, when Statistics Canada publishes the new CCOFOG reference
  year, the provincial shares need regenerating. There is a script that pulls
  the StatCan API, asserts the category hierarchy still partitions correctly,
  and rounds so each jurisdiction sums to exactly 100. It lives with the source,
  not in this package.
- **Each winter**, when CRA confirms the following year's brackets, the tax
  tables need updating.

Both currently run on my side, and I will keep doing that. Flagging it because
"who updates this in eleven months" is a fair question to ask before you agree to
host something, and the answer should not be silence.

---

## Provenance

Built by Jason Kirby. The tax and spending logic was written with Claude and
independently cross-checked: a separate implementation of the same arithmetic
was run against the app's own functions across all 13 jurisdictions and a range
of incomes, and the spending breakdown was verified to foot for all 156
province × income combinations. That verification harness, and the workbook now
with the outside reviewers, are kept alongside the source.
