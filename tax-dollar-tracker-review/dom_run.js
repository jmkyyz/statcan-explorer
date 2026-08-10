// Minimal DOM + Chart.js stub so the app's REAL handleCalculate can run unmodified.
const els = {};
const mk = (id) => (els[id] = { id, value:'', textContent:'', innerHTML:'', style:{},
  appendChild(c){ (this.children||(this.children=[])).push(c); },
  scrollIntoView(){}, });
['income','province','form-error','stat-total','stat-income-sub','stat-federal','stat-fed-pct',
 'stat-provincial','stat-prov-pct','stat-rate','results','table-body','chart-wrap','taxChart'].forEach(mk);

global.document = {
  getElementById: id => els[id] || mk(id),
  createElement: () => ({ innerHTML:'', className:'', style:{} }),
  addEventListener: () => {},
};
let chartCfg = null;
global.Chart = class { constructor(_, cfg){ chartCfg = cfg; } destroy(){} };

const src = require('fs').readFileSync('full_script.js','utf8');
require('vm').runInThisContext(src);  // executes the app's own script in global scope

function run(income, prov) {
  els['income'].value = String(income);
  els['province'].value = prov;
  els['table-body'].innerHTML = '';
  els['table-body'].children = [];
  handleCalculate();
  return {
    total: els['stat-total'].textContent,
    fed:   els['stat-federal'].textContent,
    prov:  els['stat-provincial'].textContent,
    rate:  els['stat-rate'].textContent,
    err:   els['form-error'].style.display === 'block' ? els['form-error'].textContent : null,
    shown: els['results'].style.display,
    rows:  (els['table-body'].children || []).length,
    chartRows: chartCfg ? chartCfg.data.labels.length : 0,
  };
}

console.log('Running the app\'s real handleCalculate() through a DOM stub\n');
console.log('income     prov   total       federal     provincial   eff.rate  results  rows  chart');
for (const [inc, p] of [[60000,'ON'],[100000,'ON'],[120000,'ON'],[250000,'ON'],
                        [100000,'QC'],[300000,'YT'],[85000,'AB'],[45000,'NS']]) {
  const r = run(inc, p);
  console.log(`${String(inc).padEnd(10)} ${p}     ${r.total.padEnd(11)} ${r.fed.padEnd(11)} ${r.prov.padEnd(12)} ${r.rate.padEnd(9)} ${r.shown.padEnd(8)} ${String(r.rows).padEnd(5)} ${r.chartRows}`);
}

console.log('\nValidation paths:');
const e1 = run('', 'ON');           console.log('  empty income   ->', JSON.stringify(e1.err));
els['income'].value='80000'; els['province'].value='';
handleCalculate();                  console.log('  no province    ->', JSON.stringify(els['form-error'].textContent));
const e3 = run(0, 'ON');            console.log('  income 0       -> fed subtitle:', JSON.stringify(els['stat-fed-pct'].textContent));

console.log('\nChart end-label total (checks chart._totalTax is set before first draw):');
console.log('  chart datasets:', chartCfg.data.datasets.map(d=>d.label).join(', '), '| categories:', chartCfg.data.labels.length);
