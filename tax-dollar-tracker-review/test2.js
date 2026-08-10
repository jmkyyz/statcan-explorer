const { FED_BRACKETS, FED_BPA, PROVINCES } = require('./core.js');
const $ = n => '$' + Math.round(n).toLocaleString('en-CA');

// unrounded replica of calcTax
function raw(income, brackets, bpa) {
  let tax = 0, prev = 0;
  for (const [limit, rate] of brackets) {
    if (income <= prev) break;
    tax += (Math.min(income, limit === Infinity ? income : limit) - prev) * rate;
    if (limit === Infinity) break;
    prev = limit;
  }
  return Math.max(0, tax - bpa * brackets[0][1]);
}
function totalRaw(income, k) {
  let fed = raw(income, FED_BRACKETS, FED_BPA);
  if (k === 'QC') fed *= (1 - 0.165);
  let prov = raw(income, PROVINCES[k].brackets, PROVINCES[k].bpa);
  if (k === 'ON') prov += Math.max(0, prov - 7307) * 0.20 + Math.max(0, prov - 7446) * 0.36;
  return fed + prov;
}

console.log('═'.repeat(88));
console.log('TEST 2b — Structural breaks in the COMBINED marginal rate (unrounded, $10 step)');
console.log('═'.repeat(88));
for (const k of Object.keys(PROVINCES)) {
  const drops = [];
  let prevMR = null;
  for (let inc = 20000; inc <= 600000; inc += 10) {
    const mr = (totalRaw(inc, k) - totalRaw(inc - 10, k)) / 10;
    if (prevMR !== null && mr < prevMR - 1e-9) {
      drops.push({ inc, from: prevMR, to: mr });
    }
    prevMR = mr;
  }
  if (drops.length) {
    for (const d of drops) {
      console.log(`  ✗ ${k}: marginal rate FALLS ${(d.from*100).toFixed(2)}% → ${(d.to*100).toFixed(2)}% at income $${d.inc.toLocaleString()}`);
    }
  }
}
console.log('  (only genuine non-monotonic breaks listed)\n');

console.log('═'.repeat(88));
console.log('YUKON — dollar impact of the extra 12.93% bracket at $253,414');
console.log('═'.repeat(88));
{
  const coded = PROVINCES.YT.brackets;
  const fixed = [[57375,.064],[114750,.09],[177882,.109],[500000,.128],[Infinity,.15]];
  console.log('  income        coded YT tax   5-bracket YT tax   overstatement');
  for (const inc of [200000, 253414, 300000, 400000, 500000, 600000, 1000000]) {
    const c = raw(inc, coded, 16129), f = raw(inc, fixed, 16129);
    console.log(`  ${$(inc).padEnd(12)} ${$(c).padStart(12)}   ${$(f).padStart(16)}   ${$(c-f).padStart(13)}`);
  }
  console.log('\n  Note the coded schedule also charges 12.93% then 12.80% — a marginal rate that goes DOWN,');
  console.log('  which no Canadian rate schedule does. Peak overstatement is at $500,000.');
}
console.log('');

console.log('═'.repeat(88));
console.log('ONTARIO SURTAX — dollar impact across the income range');
console.log('═'.repeat(88));
{
  const onRaw = i => raw(i, PROVINCES.ON.brackets, PROVINCES.ON.bpa);
  const coded = t => Math.max(0,t-7307)*0.20 + Math.max(0,t-7446)*0.36;
  const alt   = t => Math.max(0,t-5710)*0.20 + Math.max(0,t-7307)*0.36;
  // income at which base ON tax crosses each threshold
  const cross = target => { let lo=0, hi=400000; for(let i=0;i<60;i++){const m=(lo+hi)/2; onRaw(m)<target?lo=m:hi=m;} return (lo+hi)/2; };
  console.log(`  ON base tax hits $5,710 at income ≈ ${$(cross(5710))}`);
  console.log(`  ON base tax hits $7,307 at income ≈ ${$(cross(7307))}`);
  console.log(`  ON base tax hits $7,446 at income ≈ ${$(cross(7446))}`);
  console.log('\n  income      base ON tax   coded surtax   surtax @5710/7307   understated by');
  for (const inc of [90000, 95000, 100000, 105000, 110000, 115000, 120000, 140000, 180000, 250000, 400000]) {
    const b = onRaw(inc);
    console.log(`  ${$(inc).padEnd(11)} ${$(b).padStart(11)}  ${$(coded(b)).padStart(12)}   ${$(alt(b)).padStart(17)}   ${$(alt(b)-coded(b)).padStart(14)}`);
  }
  console.log('\n  → The coded first threshold ($7,307) is the CORRECT SECOND threshold. Ontario taxpayers');
  console.log('    between ~$96k and ~$109k of income are shown paying $0 surtax when they owe some,');
  console.log('    and everyone above that is understated by a flat ~$369.');
}
