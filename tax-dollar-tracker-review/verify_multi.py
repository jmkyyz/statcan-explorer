import warnings, json, subprocess, shutil, openpyxl
warnings.filterwarnings('ignore')
import formulas
SRC = '/Users/JKirby/statcan-explorer/tax-dollar-tracker-review.xlsx'
TMP = 'probe.xlsx'
P = "'[probe.xlsx]TAX ENGINE'!"
order = ['AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT']
INCOMES = [18000, 24000, 30000, 37000, 48300, 60000, 72300, 100000, 120000, 200300, 300000]

js = "const{calculate}=require('./core_fixed.js');const o={};" + \
     "for(const i of %s){o[i]={};for(const k of %s){const r=calculate(i,k);o[i][k]=[r.fedTax,r.provTax];}}" % (INCOMES, order) + \
     "console.log(JSON.stringify(o));"
exp = json.loads(subprocess.check_output(['node','-e',js]).decode())

def num(x):
    try: return round(float(x))
    except: return None

bad = 0; checks = 0
print(f"{'income':>9}  {'ON premium':>10}  {'ON prov (xlsx)':>15}  {'ON prov (app)':>14}  all 13 jurisdictions")
for inc in INCOMES:
    shutil.copy(SRC, TMP)
    wb = openpyxl.load_workbook(TMP); wb['Tax Engine']['B4'] = inc; wb.save(TMP)
    sol = formulas.ExcelModel().loads(TMP).finish().calculate()
    get = lambda c: num(sol[P + c].value[0,0])
    row_bad = 0
    for i, code in enumerate(order):
        r = 7 + i
        checks += 2
        if (get(f'G{r}'), get(f'M{r}')) != tuple(exp[str(inc)][code]):
            row_bad += 1
            print(f'    MISMATCH {code}: xlsx {get(f"G{r}")}/{get(f"M{r}")} vs app {exp[str(inc)][code]}')
    bad += row_bad
    print(f"{inc:>9,}  {get('L15'):>10,}  {get('M15'):>15,}  {exp[str(inc)]['ON'][1]:>14,}  "
          f"{'all match' if row_bad==0 else str(row_bad)+' MISMATCH'}")
print(f'\n{checks} values compared across {len(INCOMES)} incomes x 13 jurisdictions — mismatches: {bad}')
