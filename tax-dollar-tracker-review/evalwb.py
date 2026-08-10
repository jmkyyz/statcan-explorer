import sys, warnings, json
warnings.filterwarnings('ignore')
import formulas
fn = '/Users/JKirby/statcan-explorer/tax-dollar-tracker-review.xlsx'
xl = formulas.ExcelModel().loads(fn).finish()
sol = xl.calculate()
res = {}
errs = []
for k, v in sol.items():
    try:
        val = v.value[0, 0]
    except Exception:
        continue
    key = k.upper()
    res[key] = val
    s = str(val)
    if s.startswith('#') and s not in ('#EMPTY',):
        errs.append((key, s))
print('cells evaluated:', len(res))
print('ERRORS:', len(errs))
for k, v in errs[:60]:
    print('  ', k, '->', v)
json.dump({k: (str(v)) for k, v in res.items()}, open('solved.json','w'))
