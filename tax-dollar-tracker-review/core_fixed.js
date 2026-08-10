// 2025 federal brackets — lowest rate reduced 15% → 14.5% per 2025 federal budget
// Source: TaxTips.ca / CRA 2025
const FED_BRACKETS = [
  [57375,    0.145],
  [114750,   0.205],
  [177882,   0.26],
  [253414,   0.29],
  [Infinity, 0.33],
];
const FED_BPA = 16129;  // BPA for income ≤ $177,882; phases down to $14,538 above that (not modelled)

const PROVINCES = {
  AB: {
    name: 'Alberta',
    // New 8% entry bracket on first $60,000 introduced Jan 1 2025
    brackets: [[60000,.08],[151234,.10],[181481,.12],[241974,.13],[362961,.14],[Infinity,.15]],
    bpa: 22323,
    // chtPct: 2023-24 CHT allocation ($49.4B equal per-capita) as % of 2022-23 total provincial expenditure ($62.1B)
    chtPct: 9.4,
    spending: { health:43, socialEI:7,  debt:3,  admin:5, education:18, transport:8,  justice:5, housing:3, environment:4, other:4 },
  },
  BC: {
    name: 'British Columbia',
    brackets: [[49279,.0506],[98560,.077],[113158,.105],[137407,.1229],[186306,.147],[259829,.168],[Infinity,.205]],
    bpa: 12932,
    // chtPct: CHT $6.81B / total exp $82B
    chtPct: 8.3,
    spending: { health:39, socialEI:10, debt:5,  admin:5, education:18, transport:7,  justice:5, housing:3, environment:4, other:4 },
  },
  MB: {
    name: 'Manitoba',
    // 2025 Manitoba Budget froze indexation; thresholds updated to $47k/$100k
    brackets: [[47000,.108],[100000,.1275],[Infinity,.174]],
    bpa: 15780,
    // chtPct: CHT $1.77B / total exp ~$20B
    chtPct: 8.9,
    spending: { health:37, socialEI:11, debt:8,  admin:5, education:20, transport:7,  justice:5, housing:2, environment:3, other:2 },
  },
  NB: {
    name: 'New Brunswick',
    // Substantially restructured for 2025 — reduced top rate, new thresholds
    brackets: [[51306,.094],[102614,.14],[190060,.16],[Infinity,.195]],
    bpa: 13396,
    // chtPct: CHT $1.05B / total exp $11.3B
    chtPct: 9.3,
    spending: { health:42, socialEI:8,  debt:9,  admin:4, education:17, transport:7,  justice:5, housing:2, environment:4, other:2 },
  },
  NL: {
    name: 'Newfoundland and Labrador',
    brackets: [[44192,.087],[88382,.145],[157792,.158],[220910,.178],[282214,.198],[564429,.208],[1128858,.213],[Infinity,.218]],
    bpa: 11067,
    // chtPct: CHT $0.68B / total exp $9.4B
    chtPct: 7.2,
    spending: { health:42, socialEI:6,  debt:9,  admin:4, education:16, transport:9,  justice:5, housing:2, environment:5, other:2 },
  },
  NS: {
    name: 'Nova Scotia',
    brackets: [[30507,.0879],[61015,.1495],[95883,.1667],[154650,.175],[Infinity,.21]],
    bpa: 11744,
    // chtPct: CHT $1.32B / total exp $13.2B
    chtPct: 10.0,
    spending: { health:43, socialEI:8,  debt:8,  admin:4, education:17, transport:7,  justice:5, housing:2, environment:4, other:2 },
  },
  NT: {
    name: 'Northwest Territories',
    brackets: [[51964,.059],[103930,.086],[168967,.122],[Infinity,.1405]],
    bpa: 17842,
    chtPct: 0, // territories receive equivalent health funding via TFF, not CHT directly
    spending: { health:30, socialEI:7,  debt:2,  admin:5, education:22, transport:14, justice:8, housing:3, environment:7, other:2 },
  },
  NU: {
    name: 'Nunavut',
    brackets: [[54707,.04],[109413,.07],[177881,.09],[Infinity,.115]],
    bpa: 19274,
    chtPct: 0,
    spending: { health:29, socialEI:8,  debt:1,  admin:5, education:25, transport:12, justice:8, housing:4, environment:6, other:2 },
  },
  ON: {
    name: 'Ontario',
    brackets: [[52886,.0505],[105775,.0915],[150000,.1116],[220000,.1216],[Infinity,.1316]],
    bpa: 12747,
    // chtPct: CHT $19.0B / total exp $187.1B
    chtPct: 10.2,
    spending: { health:40, socialEI:11, debt:9,  admin:5, education:18, transport:5,  justice:5, housing:3, environment:3, other:1 },
  },
  PE: {
    name: 'Prince Edward Island',
    // Restructured for 2025 with new rates and thresholds; surtax eliminated
    brackets: [[33328,.095],[64656,.1347],[105000,.166],[140000,.1762],[Infinity,.19]],
    bpa: 14650,
    // chtPct: CHT $0.22B / total exp $2.7B
    chtPct: 8.2,
    spending: { health:40, socialEI:7,  debt:7,  admin:5, education:20, transport:8,  justice:5, housing:2, environment:4, other:2 },
  },
  QC: {
    name: 'Quebec',
    brackets: [[53255,.14],[106495,.19],[129590,.24],[Infinity,.2575]],
    bpa: 18571,
    // chtPct: CHT $11.2B / total exp $136.6B
    chtPct: 8.2,
    spending: { health:40, socialEI:12, debt:7,  admin:4, education:20, transport:6,  justice:4, housing:2, environment:3, other:2 },
  },
  SK: {
    name: 'Saskatchewan',
    // BPA boosted by Dec 2024 Affordability Measures
    brackets: [[53463,.105],[152750,.125],[Infinity,.145]],
    bpa: 19491,
    // chtPct: CHT $1.54B / total exp $19.0B
    chtPct: 8.1,
    spending: { health:38, socialEI:6,  debt:3,  admin:6, education:19, transport:10, justice:6, housing:3, environment:5, other:4 },
  },
  YT: {
    name: 'Yukon',
    // Mirrors federal bracket thresholds up to $177,882, then 12.8% to $500,000.
    // Source: CRA Form YT428 (5011-C), 2025 — five brackets, not six.
    // Do NOT reinstate a 12.93% band at $253,414: that figure is an *effective* rate with the
    // federal BPA clawback baked in (12.8% + 1,591/75,532 × 6.4% = 12.935%), not a statutory rate.
    brackets: [[57375,.064],[114750,.09],[177882,.109],[500000,.128],[Infinity,.15]],
    // Yukon claims the federal BPA, so it phases down over $177,882–$253,414. Not modelled,
    // consistent with the federal BPA phase-down also not being modelled.
    bpa: 16129,
    chtPct: 0,
    spending: { health:28, socialEI:7,  debt:2,  admin:5, education:24, transport:16, justice:8, housing:1, environment:7, other:2 },
  },
};

// Shared spending taxonomy — 18 categories
// fedPct = % of federal tax pool; provKey = key in province spending object (null = federal-only)
const CATS = [
  // Federal % based on 2023-24 Public Accounts actuals + Budget 2025 projections
  // Key line items: Elderly benefits 14.3%, CHT 10.0% (transfer to provinces),
  // direct federal health 2.0%, PDC 9.6%, EI+CCB 10.4%,
  // CST 3.0% (transfer to provinces for social services + post-secondary),
  // equalization+TFF+fiscal arrangements (~5.8%) folded into Fiscal Transfers & Admin.
  { key:'cht',          label:'Canada Health Transfer',     fedPct:10, provKey:null          },
  { key:'health',       label:'Direct Health Spending',      fedPct: 2, provKey:'health'      },
  { key:'cst',          label:'Canada Social Transfer',      fedPct: 3, provKey:null          },
  { key:'socialEI',     label:'Social Assistance & EI',     fedPct: 7, provKey:'socialEI'    },
  { key:'oas',          label:'OAS & Retirement',            fedPct:15, provKey:null          },
  { key:'debt',         label:'Debt Servicing',              fedPct:10, provKey:'debt'        },
  { key:'admin',        label:'Fiscal Transfers & Admin',    fedPct:12, provKey:'admin'       },
  { key:'education',    label:'Education',                   fedPct: 4, provKey:'education'   },
  { key:'transport',    label:'Transportation & Infra',      fedPct: 2, provKey:'transport'   },
  { key:'indigenous',   label:'Indigenous Services',         fedPct: 5, provKey:null          },
  { key:'justice',      label:'Justice & Public Safety',     fedPct: 2, provKey:'justice'     },
  { key:'defence',      label:'National Defence',            fedPct: 5, provKey:null          },
  { key:'housing',      label:'Housing & Communities',       fedPct: 2, provKey:'housing'     },
  { key:'environment',  label:'Environment & Climate',       fedPct: 2, provKey:'environment' },
  { key:'science',      label:'Science & Innovation',        fedPct: 2, provKey:null          },
  { key:'intlDev',      label:'International Development',   fedPct: 1, provKey:null          },
  { key:'immigration',  label:'Immigration & Settlement',    fedPct: 1, provKey:null          },
  { key:'agriculture',  label:'Agriculture & Food',          fedPct: 1, provKey:null          },
  { key:'veterans',     label:'Veterans Affairs',            fedPct: 2, provKey:null          },
  { key:'other',        label:'Other',                       fedPct:12, provKey:'other'       },
];

// ═══════════════════════════════════════════════════════════════
// TAX CALCULATION
// ═══════════════════════════════════════════════════════════════

// Ontario Health Premium — a step function of taxable income, collected as Ontario income tax
// on Form ON428 line 89 and carried to T1 line 42800. Not indexed; unchanged since 2004.
// Each ramp is capped at the plateau above it, so the schedule is monotonic and continuous.
function ontarioHealthPremium(income) {
  if (income <= 20000)  return 0;
  if (income <= 25000)  return Math.min(300, (income -  20000) * 0.06);
  if (income <= 36000)  return 300;
  if (income <= 38500)  return Math.min(450, 300 + (income -  36000) * 0.06);
  if (income <= 48000)  return 450;
  if (income <= 48600)  return Math.min(600, 450 + (income -  48000) * 0.25);
  if (income <= 72000)  return 600;
  if (income <= 72600)  return Math.min(750, 600 + (income -  72000) * 0.25);
  if (income <= 200000) return 750;
  if (income <= 200600) return Math.min(900, 750 + (income - 200000) * 0.25);
  return 900;
}

function calcTax(income, brackets, bpa) {
  let tax = 0;
  let prev = 0;
  for (const [limit, rate] of brackets) {
    if (income <= prev) break;
    const slice = Math.min(income, limit === Infinity ? income : limit) - prev;
    tax += slice * rate;
    if (limit === Infinity) break;
    prev = limit;
  }
  tax -= bpa * brackets[0][1]; // BPA credit at lowest rate
  return Math.max(0, Math.round(tax));
}

function calculate(income, provKey) {
  const prov = PROVINCES[provKey];

  // ── Federal tax ───────────────────────────────────────────────
  let fedTax = calcTax(income, FED_BRACKETS, FED_BPA);

  // Quebec federal abatement: 16.5% reduction on net federal tax.
  // Quebec operates its own tax system; Ottawa returns 16.5% of federal
  // tax to compensate for the provincial tax room Quebec occupies.
  if (provKey === 'QC') {
    fedTax = Math.round(fedTax * (1 - 0.165));
  }

  // ── Provincial tax ────────────────────────────────────────────
  let provTax = calcTax(income, prov.brackets, prov.bpa);

  // Ontario surtax (2025 thresholds), then the Ontario Health Premium.
  // Source: CRA Form ON428 (5006-C) — surtax at lines 66-68, health premium at line 89.
  //   20% on Ontario tax over $5,710
  // + 36% on Ontario tax over $7,307  (additional, so 56% total above $7,307)
  // The premium is added after the surtax, as on the form, and flows to T1 line 42800.
  if (provKey === 'ON') {
    const surtax = Math.max(0, provTax - 5710) * 0.20
                 + Math.max(0, provTax - 7307) * 0.36;
    provTax = Math.round(provTax + surtax) + ontarioHealthPremium(income);
  }

  // PEI surtax eliminated for 2024 and later — replaced by restructured bracket rates

  // ── Spending allocation ───────────────────────────────────────
  const total = fedTax + provTax;

  // Subtract CHT-funded portion from provincial health, then renormalize
  // so provincial category amounts still distribute the full provTax.
  // chtPct is CHT allocation as % of total provincial expenditure (2023-24 CHT / 2022-23 actuals).
  const rawCats = CATS.map(cat => {
    const fedAmt     = Math.round((cat.fedPct / 100) * fedTax);
    const rawPct     = cat.provKey ? (prov.spending[cat.provKey] || 0) : 0;
    const adjProvPct = (cat.key === 'health')
      ? Math.max(0, rawPct - (prov.chtPct || 0))
      : rawPct;
    return { label: cat.label, fedAmt, adjProvPct };
  });

  const totalAdjPct = rawCats.reduce((s, c) => s + c.adjProvPct, 0);

  const catData = rawCats.map(c => {
    const provAmt = (totalAdjPct > 0 && c.adjProvPct > 0)
      ? Math.round((c.adjProvPct / totalAdjPct) * provTax)
      : 0;
    return {
      label:    c.label,
      fedAmt:   c.fedAmt,
      provAmt,
      combined: c.fedAmt + provAmt,
      pct:      total > 0 ? (c.fedAmt + provAmt) / total : 0,
    };
  }).sort((a, b) => b.combined - a.combined);

  return { fedTax, provTax, total, catData };
}
module.exports = { FED_BRACKETS, FED_BPA, PROVINCES, CATS, calcTax, calculate, ontarioHealthPremium };
