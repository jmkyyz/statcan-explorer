const A = require('./core.js');        // before
const B = require('./core_fixed.js');  // after
const $ = n => '$' + Math.round(n).toLocaleString('en-CA');
let fail = 0;
const chk = (name, got, want, tol=0) => {
  const ok = Math.abs(got - want) <= tol;
  if (!ok) { fail++; console.log(`  ✗ ${name}: got ${got}, expected ${want}`); }
  return ok;
};

console.log('═'.repeat(86));
console.log('1. Ontario Health Premium — every breakpoint in the CRA schedule');
console.log('═'.repeat(86));
const OHP = [
  [19999,0],[20000,0],[22500,150],[25000,300],[30000,300],[36000,300],
  [37250,375],[38500,450],[43000,450],[48000,450],[48300,525],[48600,600],
  [60000,600],[72000,600],[72300,675],[72600,750],[100000,750],[200000,750],
  [200300,825],[200600,900],[500000,900],
];
for (const [inc, want] of OHP) chk(`OHP(${inc})`, B.ontarioHealthPremium(inc), want, 0.005);
console.log(`  ${OHP.length} breakpoints checked — ${fail === 0 ? 'all correct' : fail + ' FAILED'}`);

// monotonic + continuous
let prev = -1, mono = true;
for (let i = 0; i <= 250000; i += 25) { const v = B.ontarioHealthPremium(i); if (v < prev - 1e-9) mono = false; prev = v; }
console.log(`  monotonic across $0-$250,000: ${mono ? 'yes' : 'NO'}`);
let maxJump = 0;
for (let i = 25; i <= 250000; i += 25) maxJump = Math.max(maxJump, B.ontarioHealthPremium(i) - B.ontarioHealthPremium(i-25));
console.log(`  largest step over a $25 income increment: $${maxJump.toFixed(2)} (no cliff = continuous)`);

console.log('\n' + '═'.repeat(86));
console.log('2. Ontario surtax — now matches Form ON428 lines 66-68');
console.log('═'.repeat(86));
const onBase = i => A.calcTax(i, A.PROVINCES.ON.brackets, A.PROVINCES.ON.bpa);
const want = t => Math.max(0,t-5710)*0.20 + Math.max(0,t-7307)*0.36;
console.log('  income      base ON tax   surtax now   expected   OHP now   ON total before -> after   change');
for (const inc of [60000, 90000, 100000, 110000, 120000, 150000, 250000]) {
  const b = onBase(inc);
  const sNow = B.calculate(inc,'ON').provTax - b - B.ontarioHealthPremium(inc);
  chk(`surtax@${inc}`, sNow, Math.round(b + want(b)) - b, 1);
  const before = A.calculate(inc,'ON').provTax, after = B.calculate(inc,'ON').provTax;
  console.log(`  ${$(inc).padEnd(11)} ${$(b).padStart(11)} ${$(sNow).padStart(12)} ${$(want(b)).padStart(10)} ${$(B.ontarioHealthPremium(inc)).padStart(9)}   ${$(before).padStart(8)} -> ${$(after).padStart(8)}   ${$(after-before).padStart(7)}`);
}

console.log('\n' + '═'.repeat(86));
console.log('3. Yukon — phantom bracket removed');
console.log('═'.repeat(86));
console.log(`  bracket count: ${A.PROVINCES.YT.brackets.length} -> ${B.PROVINCES.YT.brackets.length}`);
let mono2 = true;
for (let i = 1; i < B.PROVINCES.YT.brackets.length; i++)
  if (B.PROVINCES.YT.brackets[i][1] < B.PROVINCES.YT.brackets[i-1][1]) mono2 = false;
console.log(`  marginal rates now strictly increasing: ${mono2 ? 'yes' : 'NO'}`);
console.log('  income        YT tax before   YT tax after   change');
for (const inc of [200000, 253414, 300000, 500000, 1000000]) {
  const a = A.calculate(inc,'YT').provTax, b = B.calculate(inc,'YT').provTax;
  console.log(`  ${$(inc).padEnd(12)} ${$(a).padStart(13)} ${$(b).padStart(14)} ${$(b-a).padStart(8)}`);
}

console.log('\n' + '═'.repeat(86));
console.log('4. Regression — nothing else moved');
console.log('═'.repeat(86));
let moved = [];
for (const k of Object.keys(B.PROVINCES)) {
  for (let inc = 5000; inc <= 600000; inc += 5000) {
    const a = A.calculate(inc,k), b = B.calculate(inc,k);
    if (a.fedTax !== b.fedTax) moved.push(`${k}@${inc} federal ${a.fedTax}->${b.fedTax}`);
    if (a.provTax !== b.provTax && !['ON','YT'].includes(k)) moved.push(`${k}@${inc} prov ${a.provTax}->${b.provTax}`);
  }
}
console.log(moved.length ? '  UNEXPECTED CHANGES:\n   ' + moved.slice(0,10).join('\n   ')
                         : '  Federal tax unchanged everywhere; provincial tax unchanged outside ON and YT. ✓');

console.log('\n' + '═'.repeat(86));
console.log('5. Structural checks still hold');
console.log('═'.repeat(86));
let bad = [];
for (const k of Object.keys(B.PROVINCES)) {
  let prevT = -1;
  for (let inc = 1000; inc <= 600000; inc += 1000) {
    const t = B.calculate(inc,k).total;
    if (t < prevT) bad.push(`${k} total tax falls at $${inc}`);
    prevT = t;
  }
  const br = B.PROVINCES[k].brackets;
  for (let i = 1; i < br.length; i++) if (br[i][1] < br[i-1][1]) bad.push(`${k} rate drops at bracket ${i+1}`);
}
console.log(bad.length ? '  ' + bad.join('\n  ') : '  Total tax monotonic in income for all 13; all rate schedules increasing. ✓');

// allocation still distributes the full provincial tax
let allocBad = 0;
for (const k of Object.keys(B.PROVINCES)) {
  const r = B.calculate(120000, k);
  const sp = r.catData.reduce((s,c)=>s+c.provAmt,0);
  if (Math.abs(sp - r.provTax) > 6) { allocBad++; console.log(`  ${k}: provincial allocation ${sp} vs tax ${r.provTax}`); }
}
console.log(`  Allocation still distributes full provincial tax incl. the premium: ${allocBad === 0 ? 'yes ✓' : 'NO'}`);

console.log('\n' + (fail === 0 ? '✓ ALL ASSERTIONS PASSED' : `✗ ${fail} ASSERTION(S) FAILED`));
