const { FED_BRACKETS, FED_BPA, PROVINCES, CATS, calcTax, calculate } = require('./core.js');

const $ = n => '$' + Math.round(n).toLocaleString('en-CA');
let issues = [];
const flag = (sev, s) => { issues.push(`[${sev}] ${s}`); };

console.log('═'.repeat(90));
console.log('TEST 1 — Monotonicity of marginal rates within each bracket schedule');
console.log('═'.repeat(90));
function checkMono(name, brackets) {
  for (let i = 1; i < brackets.length; i++) {
    if (brackets[i][1] < brackets[i-1][1]) {
      const msg = `${name}: marginal rate DROPS from ${(brackets[i-1][1]*100).toFixed(2)}% (to $${brackets[i-1][0].toLocaleString()}) to ${(brackets[i][1]*100).toFixed(2)}%`;
      console.log('  ✗ ' + msg); flag('HIGH', msg);
    }
    if (brackets[i][0] <= brackets[i-1][0]) {
      const msg = `${name}: bracket thresholds not increasing at index ${i}`;
      console.log('  ✗ ' + msg); flag('HIGH', msg);
    }
  }
}
checkMono('FEDERAL', FED_BRACKETS);
for (const [k, p] of Object.entries(PROVINCES)) checkMono(k, p.brackets);
console.log('  (no output above = all monotonic)\n');

console.log('═'.repeat(90));
console.log('TEST 2 — Effective marginal rate scan: does total tax ever fall as income rises?');
console.log('═'.repeat(90));
for (const k of Object.keys(PROVINCES)) {
  let prevTotal = -1, prevMR = null, worst = null;
  for (let inc = 1000; inc <= 700000; inc += 1000) {
    const r = calculate(inc, k);
    if (r.total < prevTotal) {
      const msg = `${k}: total tax DECREASES between $${(inc-1000).toLocaleString()} and $${inc.toLocaleString()}`;
      console.log('  ✗ ' + msg); flag('HIGH', msg); break;
    }
    const mr = (r.total - prevTotal) / 1000;
    if (prevMR !== null && mr < prevMR - 0.0005 && prevTotal >= 0) {
      if (!worst || (prevMR - mr) > worst.drop) worst = { inc, from: prevMR, to: mr, drop: prevMR - mr };
    }
    prevMR = mr; prevTotal = r.total;
  }
  if (worst) {
    const msg = `${k}: combined MARGINAL rate falls from ${(worst.from*100).toFixed(2)}% to ${(worst.to*100).toFixed(2)}% at ~$${worst.inc.toLocaleString()}`;
    console.log('  ⚠ ' + msg); flag('HIGH', msg);
  }
}
console.log('');

console.log('═'.repeat(90));
console.log('TEST 3 — Ontario surtax: coded vs. widely-published 2025 thresholds');
console.log('═'.repeat(90));
const onBase = i => calcTax(i, PROVINCES.ON.brackets, PROVINCES.ON.bpa);
const codedSur = t => Math.max(0, t - 7307) * 0.20 + Math.max(0, t - 7446) * 0.36;
const altSur   = t => Math.max(0, t - 5710) * 0.20 + Math.max(0, t - 7307) * 0.36;
console.log('  income     ON base tax   coded surtax   alt(5710/7307)   difference');
for (const inc of [60000, 80000, 100000, 120000, 150000, 200000, 300000]) {
  const b = onBase(inc);
  const c = codedSur(b), a = altSur(b);
  console.log(`  ${$(inc).padEnd(10)} ${$(b).padStart(11)}  ${$(c).padStart(12)}   ${$(a).padStart(13)}   ${$(a-c).padStart(10)}`);
}
console.log('');

console.log('═'.repeat(90));
console.log('TEST 4 — Category amounts must sum to the reported totals (rounding drift)');
console.log('═'.repeat(90));
let maxFedDrift = 0, maxProvDrift = 0, maxPctDrift = 0;
for (const k of Object.keys(PROVINCES)) {
  for (const inc of [35000, 60000, 85000, 120000, 175000, 250000, 500000]) {
    const r = calculate(inc, k);
    const sf = r.catData.reduce((s,c)=>s+c.fedAmt,0);
    const sp = r.catData.reduce((s,c)=>s+c.provAmt,0);
    const sPct = r.catData.reduce((s,c)=>s+c.pct,0);
    maxFedDrift  = Math.max(maxFedDrift,  Math.abs(sf - r.fedTax));
    maxProvDrift = Math.max(maxProvDrift, Math.abs(sp - r.provTax));
    maxPctDrift  = Math.max(maxPctDrift,  Math.abs(sPct - 1));
  }
}
console.log(`  max |Σ federal category − Federal total|    = $${maxFedDrift}`);
console.log(`  max |Σ provincial category − Prov. total|   = $${maxProvDrift}`);
console.log(`  max |Σ of "% of Total Tax" column − 100%|   = ${(maxPctDrift*100).toFixed(3)} pp`);
if (maxFedDrift || maxProvDrift) flag('LOW', `Category columns do not foot to the Total row (fed off by up to $${maxFedDrift}, prov up to $${maxProvDrift}); the table shows a Total row that does not equal the sum of the rows above it.`);
console.log('');

console.log('═'.repeat(90));
console.log('TEST 5 — CHT renormalization: what does it actually do to the split?');
console.log('═'.repeat(90));
console.log('  For ON @ $100,000 — provincial share of each category, before vs. after the CHT adjustment');
{
  const prov = PROVINCES.ON;
  const raw = prov.spending;
  const adj = {}; let tot = 0;
  for (const [key, v] of Object.entries(raw)) { adj[key] = key === 'health' ? Math.max(0, v - prov.chtPct) : v; tot += adj[key]; }
  console.log('  category      raw %   adj %   renormalized %   change vs raw');
  for (const key of Object.keys(raw)) {
    const rn = adj[key] / tot * 100;
    console.log(`  ${key.padEnd(13)} ${String(raw[key]).padStart(4)}%  ${adj[key].toFixed(1).padStart(5)}%   ${rn.toFixed(2).padStart(12)}%   ${(rn - raw[key] >= 0 ? '+' : '') + (rn - raw[key]).toFixed(2)} pp`);
  }
  console.log(`  renorm denominator = ${tot.toFixed(1)} (was 100)`);
  flag('MED', 'The CHT adjustment subtracts the CHT share from health and then renormalizes to 100%, which does not remove those dollars — it REDISTRIBUTES them to every other provincial category. Every non-health provincial category is inflated by ~10% relative as a side effect of a health-only correction.');
}
console.log('');

console.log('═'.repeat(90));
console.log('TEST 6 — Edge cases');
console.log('═'.repeat(90));
{
  const r0 = calculate(0, 'ON');
  console.log(`  income $0 → fed ${r0.fedTax}, prov ${r0.provTax}, total ${r0.total}; "% of income" = ${(r0.fedTax/0*100)}`);
  if (!isFinite(r0.fedTax/0) || isNaN(r0.fedTax/0)) flag('LOW', 'Income of 0 passes validation (only negatives are rejected) and the Federal/Provincial stat cards then divide by zero, rendering "NaN%".');

  const rBig = calculate(2000000, 'ON');
  console.log(`  income $2,000,000 (form max) → total ${$(rBig.total)}, eff rate ${(rBig.total/2000000*100).toFixed(1)}%`);

  // BPA credit larger than tax owed
  const rLow = calculate(12000, 'AB');
  console.log(`  AB @ $12,000 → prov tax ${$(rLow.provTax)} (BPA $22,323 exceeds income — correctly floored at 0)`);

  // does anyone pay provincial tax below the federal threshold
  console.log('\n  First dollar of tax owed, by jurisdiction (tax-free threshold implied by the model):');
  for (const k of Object.keys(PROVINCES)) {
    let fedAt = null, provAt = null;
    for (let i = 1000; i <= 60000; i += 100) {
      const r = calculate(i, k);
      if (fedAt === null && r.fedTax > 0) fedAt = i;
      if (provAt === null && r.provTax > 0) provAt = i;
      if (fedAt && provAt) break;
    }
    console.log(`    ${k}: federal tax starts ~${$(fedAt)}, provincial tax starts ~${provAt ? $(provAt) : '>60k'}`);
  }
}
console.log('');

console.log('═'.repeat(90));
console.log('TEST 7 — Federal category percentages vs. the dollar line items the docs cite');
console.log('═'.repeat(90));
{
  const DENOM = 544; // $B, as stated in methodology
  const claims = [
    ['Canada Health Transfer',   10, 54.7,  'CHT $54.7B'],
    ['Direct Health Spending',    2, 11.0,  'Health Canada + PHAC ~$11B'],
    ['Canada Social Transfer',    3, 15.9,  'CST $15.9B'],
    ['Social Assistance & EI',    7, 60.6,  'EI ~$33B + CCB ~$27B (app text says $60.6B)'],
    ['OAS & Retirement',         15, 83.1,  'OAS $68.4B + GIS $14.7B'],
    ['Debt Servicing',           10, 55.6,  'Public debt charges $55.6B'],
    ['Fiscal Transfers & Admin', 12, 31.7,  'Equalization $21.9B + TFF $4.2B + other fiscal ~$5.6B (excl. unquantified "departmental operations")'],
  ];
  console.log('  category                    coded %   cited $B   implied %   gap (pp)   line items');
  for (const [label, coded, dollars, note] of claims) {
    const implied = dollars / DENOM * 100;
    const gap = implied - coded;
    const mark = Math.abs(gap) >= 1.5 ? ' ✗' : '  ';
    console.log(`${mark} ${label.padEnd(26)} ${String(coded).padStart(5)}%  ${dollars.toFixed(1).padStart(8)}   ${implied.toFixed(1).padStart(8)}%   ${(gap>=0?'+':'')+gap.toFixed(1).padStart(6)}   ${note}`);
    if (Math.abs(gap) >= 1.5) flag('HIGH', `Federal "${label}": coded at ${coded}% but the line items the methodology itself cites ($${dollars}B of $${DENOM}B) imply ${implied.toFixed(1)}% — a gap of ${gap.toFixed(1)} pp.`);
  }
  const sum = CATS.reduce((s,c)=>s+c.fedPct,0);
  console.log(`\n  Σ of all coded federal percentages = ${sum}%  ${sum===100?'✓':'✗'}`);
}
console.log('');

console.log('═'.repeat(90));
console.log('TEST 8 — Internal contradictions between code comments, app text and methodology');
console.log('═'.repeat(90));
const contradictions = [
  ['Social Assistance & EI', 'code comment (line 560): "EI+CCB 10.4%"', 'CATS fedPct: 7', 'methodology table: 7%'],
  ['OAS & Retirement',       'code comment: "Elderly benefits 14.3%"',  'CATS fedPct: 15', 'methodology table: 15%'],
  ['Debt Servicing',         'code comment: "PDC 9.6%"',                'CATS fedPct: 10', 'methodology table: 10%'],
  ['Equalization + TFF',     'app Sources text: "$31.7B"',              'methodology: "$21.9B + $4.2B = $26.1B"', 'differ by $5.6B'],
  ['CHT vintage',            'federal column: CHT $54.7B',              'provincial adjustment: CHT $49.4B (2023-24)', 'two different CHT years used in one calculation'],
  ['AB chtPct comment',      'code line 451: "$49.4B equal per-capita ... as % of ... $62.1B"', '49.4/62.1 = 79.5%, not 9.4%', 'the comment cites the NATIONAL CHT envelope where Alberta\'s ~$5.8B share belongs'],
];
for (const [cat, a, b, c] of contradictions) {
  console.log(`  • ${cat}`);
  console.log(`      ${a}`);
  console.log(`      ${b}`);
  console.log(`      → ${c}`);
  flag('MED', `${cat}: ${a} vs ${b} — ${c}`);
}
console.log('');

console.log('═'.repeat(90));
console.log('ISSUE LOG');
console.log('═'.repeat(90));
issues.forEach((s,i) => console.log(`${String(i+1).padStart(2)}. ${s}`));
