const { FED_BRACKETS, FED_BPA, PROVINCES, CATS } = require('./core_fixed.js');
const BIG = 99999999;
const norm = b => b.map(([lim, rate]) => [lim === Infinity ? BIG : lim, rate]);
const out = {
  fedBrackets: norm(FED_BRACKETS),
  fedBpa: FED_BPA,
  provinces: Object.fromEntries(Object.entries(PROVINCES).map(([k, p]) => [k, {
    name: p.name, brackets: norm(p.brackets), bpa: p.bpa, chtPct: p.chtPct, spending: p.spending,
  }])),
  cats: CATS,
};
console.log(JSON.stringify(out, null, 1));
