# Provincial spending allocation — data source research

Working note for the Tax Dollar Tracker accuracy review. Companion to
`tax-dollar-tracker-review.xlsx`. Everything below was verified against downloaded
source files, not asserted from documentation.

Two questions were on the table:

1. Can we use the StatCan functional table for most of the split and infill the gaps
   (public debt charges, transportation) from other research, reducing the parent
   category to avoid double-counting?
2. What other data sources could complete the provincial side?

---

## Part 1 — what the StatCan tables can and cannot do

### The three tables, and their universes

| Table | Component detail | COFOG detail at provincial level | Consolidated? |
|---|---|---|---|
| **10-10-0005-01** (cited by the app) | Consolidated Canadian general government; **Consolidated provincial-territorial and local governments (PTLG)** — these are the *only* two | all 60 CCOFOG members | Yes |
| **10-10-0024-01** | 8 separate components incl. *Provincial and territorial governments* | **10 divisions only** | **No** |
| **10-10-0017-01** | Provincial and territorial governments | n/a — economic categories, incl. Interest expense | — |

The critical asymmetry in 10-10-0024-01, confirmed by enumerating the file:

- **Municipalities and other local public administrations** — all 60 CCOFOG members
- **Federal government** — all 60
- **Provincial and territorial governments** — 10 divisions only
- School boards, universities and colleges, health and social service institutions — 10 divisions only

Confirmed independently through the coordinate API: `ON / P&T / Public debt
transactions [7017]` and `ON / P&T / Transport [7045]` both return
`responseStatusCode 2` (no data), while divisions `701` and `704` return normally.
The sub-functions genuinely do not exist at provincial level — this is not a query error.

### Table footnotes that govern any use of 10-10-0024-01

- **FN 2** — CCOFOG excludes acquisitions of non-financial assets and consumption of
  fixed capital, because CSMA integration is still in progress.
- **FN 3** — the table is **not consolidated**. Transactions between components are not
  eliminated; a provincial grant to a health institution is counted in both and given a
  functional classification in both. StatCan "strongly advises against" component
  subtotals.
- **FN 4** — comparison between provinces for a given component is **not recommended**;
  use 10-10-0005-01 instead.
- **FN 6** — General public services [701] includes **all** debt interest, regardless of
  the function the debt was incurred for.
- **FN 5** — Government Business Enterprises are excluded by definition.

### Reconciliation between 10-10-0017-01 and 10-10-0024-01

The identity is `sum(CCOFOG divisions) == Expense − Consumption of fixed capital`,
which is exactly what FN 2 predicts.

| Era | n (province-years) | within $2M | max deviation |
|---|---|---|---|
| 2008–2014 | 91 | 37 | $993M (7.08% of expense) |
| 2015–2024 | 130 | **130** | $2M (0.10%) |

So from 2015 the two tables are the same measure to rounding, and a mixed derivation
across them is legitimate. Before 2015 it is not.

### Debt — the carve-out works

FN 6 puts all interest in division 701, and Interest expense in 10-10-0017-01 is the
same universe, same agency, same vintage. Tested across every province-year 2015–2024:
**interest never exceeds division 701**, so the residual is always positive.

2024 ($M):

| Province | 701 Gen. public services | Interest | Residual | Interest as % of 701 |
|---|---|---|---|---|
| Ontario | 21,861 | 16,139 | 5,722 | 73.8% |
| Quebec | 30,283 | 19,451 | 10,832 | 64.2% |
| Manitoba | 2,868 | 2,360 | 508 | 82.3% |
| Alberta | 7,872 | 3,654 | 4,218 | 46.4% |
| Nunavut | 500 | 13 | 487 | 2.6% |
| Yukon | 174 | 8 | 166 | 4.6% |

**Verdict: defensible.** Debt can be shown as its own row, carved out of General public
services, with the residual relabelled. Assert `interest < 701` in code so it fails
loudly if a future vintage breaks it.

### Transport — the carve-out does *not* work

The tempting derivation is `PTLG transport [7045] − municipal transport [7045]`, and it
looks good at first: school boards, universities and health institutions have **zero**
Economic affairs in all 221 province-years, so nothing else is in the way, and the
residual is positive everywhere (Ontario 2024: 17,246 − 7,085 = 10,161, against
provincial Economic affairs of 26,364).

It fails because it is a **mixed-basis subtraction**: PTLG (10-10-0005-01) is
consolidated, municipal (10-10-0024-01) is not. Measuring the elimination at division
level — `sum(unconsolidated components) − consolidated PTLG`, Economic affairs, 2024:

| Province | PTLG (cons.) | P&T | Muni | Sum (unc.) | Elimination | % |
|---|---|---|---|---|---|---|
| Ontario | 31,756 | 26,364 | 7,491 | 33,855 | 2,099 | 6.6% |
| Quebec | 19,157 | 15,636 | 5,711 | 21,347 | 2,190 | 11.4% |
| New Brunswick | 1,465 | 1,516 | 208 | 1,724 | 259 | 17.7% |
| Prince Edward Island | 428 | 494 | 21 | 515 | 87 | 20.3% |
| British Columbia | 8,551 | 7,555 | 1,279 | 8,834 | 283 | 3.3% |

In five jurisdictions (NB, PEI, NS, SK, NL) the unconsolidated provincial figure alone
**exceeds** the consolidated PTLG total. The residual therefore isn't "provincial
transport spending" — it is transport spending net of provincial→municipal transfers.
It drops precisely the provincial transit money a Toronto reader would care most about.

A validation that looks reassuring but isn't: for functions only municipalities perform,
PTLG ≈ municipal within ~1% (fire protection ON 2,631 vs 2,599; street lighting 188 vs
189; waste water 2,252 vs 2,259). That holds because provinces barely fund those
functions, so there is nothing to eliminate. Transport is the opposite case, so the
test does not transfer.

**Verdict: don't.** If transport must appear, it belongs as an annotation on Economic
affairs, not a row inside the 100%.

### The taxonomy the app uses did exist — and was discontinued in 2009

Archived table **10-10-0040-01** (FMS basis, CANSIM 385-0002, 1989–2009) publishes, at
*Provincial and territorial general government* level, exactly the shape the app needs:
Transportation and communication · Debt charges · Health (with hospital, medical,
preventive sub-lines) · Education (elementary-secondary vs postsecondary separately) ·
Social services · Environment · Housing · Protection of persons and property ·
Recreation and culture · Resource conservation and industrial development. All populated
21/21 years for Ontario.

StatCan retired FMS in favour of CCOFOG after 2009. So the app's ten categories are not
arbitrary — they are FMS-shaped, and probably inherited from a pre-2009 mental model.
**There is no current StatCan table that reproduces them.** That is the root cause of
the whole problem, and it is worth stating plainly to the accountants.

---

## Part 2 — other data sources

### Finances of the Nation (Canadian Tax Foundation) — the best find, but not a solution

- <https://financesofthenation.ca/real-fedprov/>
- Dataset: <https://osf.io/xm2j5/download> (CSV, ~35MB) · User guide: <https://osf.io/w6ax8/download>
- Federal + all 13 provinces/territories, **1966–2024**, CC-licensed, built explicitly to
  be consistent and comparable across jurisdictions and over time.
- Carries an `Include_Local` flag, so provincial-only and provincial-plus-local are both
  available from one source — the exact universe control this problem needs.

**But the expenditure side has only three line items**: Total expenditure [2000],
Program expenditure [2100], Debt charges [2200]. There is no functional breakdown, so it
cannot produce the split. Verified by enumerating every `itemid` in the file.

What it *is* good for: an independent, comparable, Public-Accounts-basis measure of the
debt row across all 13 jurisdictions and 59 years, bridging the 2009 FMS/CCOFOG
discontinuity. Cross-checked against StatCan (2024, $M, provincial-only):

| Province | FON total exp. | StatCan expense | ratio | FON debt | StatCan interest | diff |
|---|---|---|---|---|---|---|
| Ontario | 206,674 | 222,400 | 0.929 | 14,795 | 16,139 | −8.3% |
| Quebec | 168,543 | 187,760 | 0.898 | 19,896 | 19,451 | +2.3% |
| British Columbia | 86,218 | 92,783 | 0.929 | 3,325 | 4,290 | −22.5% |
| Alberta | 68,970 | 74,361 | 0.928 | 3,545 | 3,654 | −3.0% |
| Nova Scotia | 16,793 | 17,075 | 0.983 | 805 | 778 | +3.5% |

The two are on different bases (Public Accounts vs CGFS) and are **not**
interchangeable. But they bracket the debt row usefully: Ontario debt servicing is
7.16% (FON) / 7.41% (StatCan CCOFOG) / 5.5% (Ontario's own Public Accounts) of
expense. The app codes **9%**. All three measures say that is too high.

### CIHI — National Health Expenditure Database (NHEX)

- <https://www.cihi.ca/en/national-health-expenditure-trends>
- Health spending by province/territory, 40+ categories, 1975–present, broken out by
  source of finance **including provincial government specifically**.
- Not a substitute for the split, but the single best independent check on the largest
  row in the tool (~40% of the provincial pie).

### Finance Canada — Fiscal Reference Tables

- <https://www.canada.ca/en/department-finance/services/publications/fiscal-reference-tables.html>
- Provincial-territorial, on **both** Public Accounts and National Accounts basis.
- Classification is **economic**, not functional: transfers to persons, transfers to
  business, interest on public debt, transfers to other levels of government. Useful for
  the debt row and as a reconciliation check; useless for the split.

### RBC — Canadian Federal and Provincial Fiscal Tables

- <https://www.rbc.com/en/economics/wp-content/uploads/sites/23/2025/11/Canadian-Federal-and-Provincial-Fiscal-Tables-Nov-2025.pdf>
- Compiled from the 13 public accounts plus budgets. Convenient aggregation, but RBC
  itself states the figures "are not strictly comparable between provinces." Treat as a
  finding aid for the underlying documents, not as an authority.

### StatCan 36-10-0450-01 — provincial economic accounts

General governments revenue, expenditure and budgetary balance. Economic categories again.

---

## Where this leaves the tool

StatCan's own published guidance is that inter-provincial comparison should use the
**consolidated PTLG** estimates, precisely because provinces delegate different functions
to municipalities. That is the bind: PTLG is the comparable universe, but it is not the
universe that answers "where does my provincial income tax go."

The most defensible construction found by this research:

- **10 CCOFOG divisions** from the *Provincial and territorial governments* component of
  10-10-0024-01 — one table, one vintage, one universe, and it matches the money
  actually being allocated;
- **plus debt** carved out of General public services using Interest expense from
  10-10-0017-01, with an assertion that it never exceeds the parent;
- **= 11 rows**, fully reproducible from two StatCan tables.

Costs, which should be disclosed rather than engineered around:

- No transport row. Transport can only be an annotation.
- Post-2015 only, if the reconciliation is to hold.
- FN 4 says don't compare provinces on this component — so the province-to-province
  comparison should be dropped or heavily caveated, which is a product decision.
- Excludes capital acquisition and consumption of fixed capital (FN 2), so it is an
  operating-expense view.

Open question for the accountants: whether an operating-expense, provincial-government-only,
non-comparable view is the right answer for a public tool, or whether the comparable
PTLG view with honest relabelling is better journalism even though it no longer answers
the literal question.
