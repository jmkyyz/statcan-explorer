#!/usr/bin/env python3
"""Build the Tax Dollar Tracker review workbook."""
import json, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.comments import Comment

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'app_data.json')))
V = json.load(open(os.path.join(HERE, 'verification.json')))
FED = json.load(open(os.path.join(HERE, 'fed.json')))
OUT = '/Users/JKirby/statcan-explorer/tax-dollar-tracker-review.xlsx'

# ── styling ───────────────────────────────────────────────────────────────
FONT = 'Arial'
H1   = Font(name=FONT, size=14, bold=True, color='FFFFFF')
H2   = Font(name=FONT, size=11, bold=True, color='FFFFFF')
BOLD = Font(name=FONT, size=10, bold=True)
BASE = Font(name=FONT, size=10)
SMALL= Font(name=FONT, size=9)
SMALLI=Font(name=FONT, size=9, italic=True)
INPUT= Font(name=FONT, size=10, bold=True, color='0000FF')
LINKF= Font(name=FONT, size=10, color='008000')

NAVY   = PatternFill('solid', fgColor='1F3864')
HDR    = PatternFill('solid', fgColor='2563EB')
YELLOW = PatternFill('solid', fgColor='FFFF00')
GREY   = PatternFill('solid', fgColor='F2F2F2')
REDF   = PatternFill('solid', fgColor='FCE4E4')
AMBER  = PatternFill('solid', fgColor='FFF2CC')
GREENF = PatternFill('solid', fgColor='E2EFDA')
BLUEF  = PatternFill('solid', fgColor='DEEBF7')

thin = Side(style='thin', color='BFBFBF')
BOX  = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical='top')
CTR  = Alignment(horizontal='center', vertical='center')

MONEY = '$#,##0'
MONEY2= '$#,##0.00'
PCT1  = '0.0%'
PCT3  = '0.000%'
PP    = '+0.0;-0.0;0.0'

wb = Workbook()
wb.remove(wb.active)

def sheet(name, widths, freeze=None, tab=None):
    ws = wb.create_sheet(name)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if freeze: ws.freeze_panes = freeze
    if tab: ws.sheet_properties.tabColor = tab
    return ws

def title(ws, text, sub, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(1, 1, text); c.font = H1; c.fill = NAVY
    c.alignment = Alignment(vertical='center', indent=1)
    ws.row_dimensions[1].height = 26
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    c = ws.cell(2, 1, sub); c.font = SMALLI; c.alignment = WRAP
    ws.row_dimensions[2].height = 30

def header(ws, row, labels, fill=HDR):
    for i, lab in enumerate(labels, 1):
        c = ws.cell(row, i, lab)
        c.font = H2; c.fill = fill; c.border = BOX
        c.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
    ws.row_dimensions[row].height = 34

def put(ws, r, c, v, font=BASE, fmt=None, fill=None, align=None, border=True):
    cell = ws.cell(r, c, v)
    cell.font = font
    if fmt:   cell.number_format = fmt
    if fill:  cell.fill = fill
    if align: cell.alignment = align
    if border:cell.border = BOX
    return cell

PROV_ORDER = ['AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT']
SPEND_KEYS = ['health','socialEI','debt','admin','education','transport','justice','housing','environment','other']
SPEND_LBL  = ['Health','Social assistance','Debt servicing','General admin','Education','Transportation','Justice','Housing','Environment','Other']

REVIEW_COLS = ['Reviewer verdict\n(OK / WRONG / UNSURE)', 'Reviewer comment']

# ══════════════════════════════════════════════════════════════════════════
# 1. README
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('README', [3, 30, 105, 30], tab='1F3864')
title(ws, 'Tax Dollar Tracker — external review workbook',
      'Prepared for third-party review of the Tax Dollar Tracker (statcan-explorer / tax-dollar-tracker.html). '
      'Every number the app uses is reproduced here, with its source, its vintage, and the arithmetic that consumes it.', 4)

r = 4
def block(heading, lines, r):
    put(ws, r, 2, heading, font=Font(name=FONT, size=11, bold=True, color='1F3864'), border=False)
    r += 1
    for a, b in lines:
        put(ws, r, 2, a, font=BOLD, align=WRAP, border=False)
        put(ws, r, 3, b, font=BASE, align=WRAP, border=False)
        ws.row_dimensions[r].height = max(14, 13 * (len(b) // 95 + 1))
        r += 1
    return r + 1

r = block('What the app does', [
    ('In one sentence',
     'The user enters an annual income and a province. The app estimates their 2025 federal and provincial income tax, '
     'then splits those two tax figures across ~20 spending categories in proportion to how the federal and provincial '
     'governments spend money overall.'),
    ('Two independent halves',
     'Half 1 is a tax calculator (bracket arithmetic — objectively right or wrong). Half 2 is a spending allocation '
     '(percentage shares drawn from public accounts — a matter of judgement and classification). They can be reviewed separately.'),
], r)

r = block('The central assumption reviewers should rule on first', [
    ('Pro-rata allocation',
     'The app allocates a person\'s INCOME TAX across TOTAL GOVERNMENT SPENDING, pro rata. This implicitly assumes every '
     'dollar of income tax funds every spending category in the same proportion as total spending.'),
    ('Why that is contestable',
     'Personal income tax is roughly 45-50% of federal revenue and only ~25% of provincial revenue. Both governments also '
     'spend more than they raise. So the tool is allocating a specific revenue stream across spending that is in fact funded '
     'by many revenue streams plus borrowing.'),
    ('Precedent',
     'This is the same method used by the UK\'s HMRC "Annual Tax Summary" and similar tools, so it is defensible — but the '
     'app never states the assumption anywhere. See Findings F-14.'),
    ('The deficit is invisible',
     'Neither the federal nor the provincial deficit is disclosed or netted out, so borrowed dollars are presented as though '
     'they were tax-funded. See Findings F-15.'),
], r)

r = block('Where the first pass landed', [
    ('The tax calculator is nearly sound',
     'Every 2025 bracket, rate and basic personal amount was checked against the filed CRA Form 428 for all 13 jurisdictions. '
     'All are correct except Yukon, which carries a sixth bracket that does not exist. Two real errors remain: the Ontario '
     'surtax thresholds are shifted by one slot, and the Ontario Health Premium is missing entirely. Together those understate '
     'a single Ontario filer on $118,000-$150,000 by roughly $950 to $1,120.'),
    ('The spending allocation is the weak half',
     'This is where the tool is most exposed. On the federal side the denominator is mis-dated by a year and the line items '
     'behind it span four fiscal years, from 2020-21 to 2025-26. On the provincial side, all four jurisdictions traced back to '
     'their own public accounts failed on multiple categories — Ontario "Other" is coded at 1% against an actual 15.6%.'),
    ('The deepest problem is not a number',
     'The provincial figures are attributed to a StatCan table whose only sub-national universe is provincial-territorial AND '
     'LOCAL government — municipalities, school boards, hospitals and universities included. And the app\'s ten-category '
     'taxonomy cannot be generated from any single StatCan table. The federal taxonomy has a parallel problem: it mixes '
     'program lines with ministry lines, so it cannot be exhaustive, which is why $15.6B of carbon rebates has no category.'),
    ('What we did not check',
     'Nine of the thirteen provincial jurisdictions were not traced to source. Given that all four that were checked failed, '
     'assume the rest are wrong until shown otherwise. See the Verification Log tab for the full boundary of what was and '
     'was not verified.'),
], r)

r = block('How to use this workbook', [
    ('Yellow cells are inputs', 'Change them and everything recalculates. Blue bold text = a hardcoded input. Black = a formula.'),
    ('Tax Engine', 'Enter one income; all 13 jurisdictions recompute from the bracket tables. Compare against your own software.'),
    ('Reviewer columns', 'Every data tab ends with "Reviewer verdict" and "Reviewer comment". Please fill these in.'),
    ('Findings tab', 'Issues already identified in a first-pass review, with severity and suggested fix. Each has a reviewer column '
     'so you can confirm, reject or requalify.'),
], r)

put(ws, r, 2, 'Tab guide', font=Font(name=FONT, size=11, bold=True, color='1F3864'), border=False); r += 1
tabs = [
    ('Findings', 'Issues found in first-pass review — start here'),
    ('Tax Brackets', 'Every 2025 bracket as coded, federal + 13 jurisdictions'),
    ('Credits and Surtax', 'Basic personal amounts, credit rates, surtaxes, Quebec abatement'),
    ('Tax Engine', 'LIVE: enter an income, see all 13 jurisdictions calculated step by step'),
    ('Federal Allocation', 'The 20 federal spending categories, their coded shares and cited line items'),
    ('Provincial Allocation', 'The 13 x 10 matrix of provincial spending shares'),
    ('CHT Adjustment', 'The Canada Health Transfer double-counting correction, and what it actually does'),
    ('Allocation Engine', 'LIVE: the full allocation arithmetic for one income and province'),
    ('Sources', 'Every source cited by the app, with vintage and reproducibility assessment'),
]
for a, b in tabs:
    put(ws, r, 2, a, font=BOLD, border=False)
    put(ws, r, 3, b, font=BASE, border=False)
    r += 1

r += 1
put(ws, r, 2, 'Legend', font=Font(name=FONT, size=11, bold=True, color='1F3864'), border=False); r += 1
for fill, lab in [(YELLOW, 'Input cell — change this'), (REDF, 'Confirmed error'), (AMBER, 'Unverified / needs a source'),
                  (GREENF, 'Verified against primary source'), (BLUEF, 'Reviewer to complete')]:
    c = put(ws, r, 2, '', fill=fill); c.border = BOX
    put(ws, r, 3, lab, font=BASE, border=False)
    r += 1

# ══════════════════════════════════════════════════════════════════════════
# 2. FINDINGS  (populated from FINDINGS list below)
# ══════════════════════════════════════════════════════════════════════════
FINDINGS = json.load(open(os.path.join(os.path.dirname(__file__), 'findings.json')))

ws = sheet('Findings', [9, 13, 14, 11, 26, 62, 62, 46, 20, 34], freeze='A4', tab='C00000')
title(ws, 'Findings — first-pass review',
      'Identified by code inspection and by re-running the app\'s own arithmetic. Severity is our assessment; please requalify '
      'in the reviewer columns. "Location" refers to tax-dollar-tracker.html unless stated. Items marked FIXED have already '
      'been corrected in the code, and the Tax Engine tab reflects the corrected version.', 10)
header(ws, 3, ['ID', 'Severity', 'Status', 'Area', 'Location', 'What is wrong', 'Evidence', 'Suggested fix'] + REVIEW_COLS)

SEV_FILL = {'HIGH': REDF, 'MEDIUM': AMBER, 'LOW': GREY, 'DESIGN': BLUEF, 'NOT A BUG': GREENF}
r = 4
for f in FINDINGS:
    status = f.get('status', 'Open')
    put(ws, r, 1, f['id'], font=BOLD, align=CTR)
    put(ws, r, 2, f['sev'], font=BOLD, fill=SEV_FILL.get(f['sev'], GREY), align=CTR)
    put(ws, r, 3, status, font=BOLD, align=CTR,
        fill=GREENF if status == 'FIXED' else (GREY if f['sev'] == 'NOT A BUG' else None))
    put(ws, r, 4, f['area'], font=BASE, align=WRAP)
    put(ws, r, 5, f['loc'], font=SMALL, align=WRAP)
    put(ws, r, 6, f['what'], font=BASE, align=WRAP)
    put(ws, r, 7, f['evidence'], font=SMALL, align=WRAP)
    put(ws, r, 8, f['fix'], font=BASE, align=WRAP)
    put(ws, r, 9, '', fill=BLUEF); put(ws, r, 10, '', fill=BLUEF)
    ws.row_dimensions[r].height = max(30, 11 * (max(len(f['what']), len(f['evidence'])) // 60 + 1))
    r += 1

# ══════════════════════════════════════════════════════════════════════════
# 3. TAX BRACKETS
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Tax Brackets', [16, 8, 9, 14, 14, 11, 22, 52, 46, 20, 34], freeze='A4', tab='2563EB')
title(ws, 'Tax brackets as coded in the app — 2025 tax year, checked against the filed CRA forms',
      'Transcribed programmatically from the app source, so this IS what the app computes. Upper bound 99,999,999 represents '
      '"no upper limit". Every jurisdiction has been checked against its 2025 Form 428 (Revenu Quebec for QC). '
      'All are now correct, including Yukon, whose phantom sixth bracket has been removed.', 11)
header(ws, 3, ['Jurisdiction', 'Code', 'Bracket', 'Lower bound', 'Upper bound', 'Rate', 'Verification verdict',
               'Verification note', 'Verified against'] + REVIEW_COLS)

BRK_START = 4
r = BRK_START
rows_by_code = {}
def add_brackets(code, name, brackets, note_fn=None):
    global r
    v = V['tax_verdicts'][code]
    ok = v['verdict'].startswith('CORRECT')
    rows_by_code[code] = (r, r + len(brackets) - 1)
    lower = 0
    for i, (upper, rate) in enumerate(brackets, 1):
        note = note_fn(i) if note_fn else ''
        bad = note.startswith('ERROR')
        put(ws, r, 1, name if i == 1 else '', font=BOLD if i == 1 else BASE)
        put(ws, r, 2, code, align=CTR)
        put(ws, r, 3, i, align=CTR)
        put(ws, r, 4, lower, fmt=MONEY, fill=REDF if bad else None)
        put(ws, r, 5, upper, fmt=MONEY, fill=REDF if bad else None)
        put(ws, r, 6, rate, fmt=PCT3, fill=REDF if bad else None)
        if i == 1:
            put(ws, r, 7, v['verdict'], font=BOLD, align=WRAP, fill=GREENF if ok else REDF)
            put(ws, r, 8, v['note'], font=SMALL, align=WRAP)
            put(ws, r, 9, v['src'], font=SMALL, align=WRAP)
        else:
            put(ws, r, 7, note if bad else '', font=SMALL, align=WRAP, fill=REDF if bad else None)
            put(ws, r, 8, ''); put(ws, r, 9, '')
        put(ws, r, 10, '', fill=BLUEF); put(ws, r, 11, '', fill=BLUEF)
        if i == 1: ws.row_dimensions[r].height = 60
        lower = upper
        r += 1

add_brackets('FED', 'Federal', D['fedBrackets'])
for code in PROV_ORDER:
    p = D['provinces'][code]
    def nf(i, code=code):
        if code == 'YT' and i == 4:
            return 'FIXED — the phantom 12.93% band at $253,414 has been removed; 12.8% now runs to $500,000. See F-13.'
        return ''
    add_brackets(code, p['name'], p['brackets'], nf)

BRK_END = r - 1
r += 1
put(ws, r, 1, 'Correct Yukon 2025 schedule per Form YT428 (5011-C) — the coded rows above now match this',
    font=Font(name=FONT, size=11, bold=True, color='548235'), border=False)
r += 1
header(ws, r, ['', 'Code', 'Bracket', 'Lower bound', 'Upper bound', 'Rate', '', '', '', '', ''])
r += 1
lower = 0
for i, (upper, rate) in enumerate(V['yt_correct_brackets'], 1):
    put(ws, r, 2, 'YT', align=CTR); put(ws, r, 3, i, align=CTR)
    put(ws, r, 4, lower, fmt=MONEY, fill=GREENF)
    put(ws, r, 5, upper, fmt=MONEY, fill=GREENF)
    put(ws, r, 6, rate, fmt=PCT3, fill=GREENF)
    lower = upper; r += 1
put(ws, r + 1, 1, f'Bracket data occupies rows {BRK_START}-{BRK_END}. The Tax Engine tab reads that range directly, '
                  f'so it reproduces the app as it now stands.',
    font=SMALLI, border=False)

# ══════════════════════════════════════════════════════════════════════════
# 4. CREDITS AND SURTAX
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Credits and Surtax', [16, 8, 13, 12, 13, 10, 13, 10, 13, 13, 13, 52, 20, 34], freeze='A4', tab='2563EB')
title(ws, 'Basic personal amounts, credit rates, surtaxes and the Quebec abatement — as coded',
      'The app values the basic personal amount credit at each jurisdiction\'s LOWEST bracket rate, which is correct. '
      'Surtax thresholds are expressed in dollars of provincial tax, not dollars of income. Ontario is the only jurisdiction '
      'with a personal income tax surtax in 2025. Its two thresholds were both wrong and have been corrected; the coded '
      'and verified columns now agree.', 14)
header(ws, 3, ['Jurisdiction', 'Code', 'Basic personal amount', 'Credit rate', 'BPA credit', 'Surtax rate 1',
                'Surtax threshold 1 (coded)', 'Surtax rate 2', 'Surtax threshold 2 (coded)',
                'Verified threshold 1', 'Verified threshold 2', 'Verification note'] + REVIEW_COLS)

CS_START = 4
r = CS_START
cs_row = {}
NOTES = {
 'FED': 'BPA $16,129 and the 14.5% credit rate are both CORRECT for 2025 — T1 line 114 reads "Federal non-refundable tax '
        'credit rate 14.5%". The phase-down to $14,538 over $177,882-$253,414 is disclosed but not modelled. The rate falls '
        'to 14% for 2026, so this needs revisiting. The new Top-up Tax Credit (line 34990) is not modelled.',
 'ON':  'FIXED — the thresholds now match Form ON428 lines 66-68 (20% over $5,710, 36% over $7,307); they were previously '
        'coded as $7,307 and $7,446. The Ontario Health Premium has also been added, using the schedule below. Still NOT '
        'modelled: the Ontario Tax Reduction ($294 basic plus $544 per child, doubled mechanism), which means Ontario tax '
        'remains overstated for low-income filers and those with dependants. See F-04, F-05 (both fixed) and F-21 (open).',
 'PE':  'Surtax confirmed eliminated for 2024 and later — no surtax line appears on Form PE428.',
 'NS':  'CORRECT as coded. Nova Scotia does NOT phase out its BPA in 2025: Budget 2025 replaced the old base-plus-supplement '
        'structure with a flat $11,744 for all filers. Note CRA\'s payroll formulas T4127 120th edition still carries the old '
        'phase-out because it predates that budget — do not apply it.',
 'MB':  'Thresholds CORRECT and must not be "fixed" — CRA\'s own 2025 summary page wrongly shows the 2026 figures of $47,564 / '
        '$101,200. Manitoba paused indexation effective 2025. Separately, Manitoba DOES phase its BPA out to zero from '
        '$200,000 to $400,000 of net income, which is not modelled. See N-01 and F-23.',
 'QC':  'Credit conversion rate of 14% confirmed on TP-1 line 377.1. The 16.5% federal abatement is applied separately — see '
        'the Tax Engine tab.',
 'YT':  'Yukon uses the FEDERAL basic personal amount, so it inherits the federal phase-down over $177,882-$253,414. Not '
        'modelled — and the coded 12.93% bracket is an attempt to embed that clawback in the rate instead. See F-13.',
}
OSC = V['on_surtax_correct']
entries = [('FED', 'Federal', D['fedBpa'], D['fedBrackets'][0][1], 0, 0, 0, 0)]
for code in PROV_ORDER:
    p = D['provinces'][code]
    if code == 'ON':
        # Post-fix coded values; these now equal the verified Form ON428 thresholds.
        entries.append((code, p['name'], p['bpa'], p['brackets'][0][1], 0.20, OSC['t1'], 0.36, OSC['t2']))
    else:
        entries.append((code, p['name'], p['bpa'], p['brackets'][0][1], 0, 0, 0, 0))

for code, name, bpa, rate, sr1, st1, sr2, st2 in entries:
    note = NOTES.get(code, 'No surtax in 2025; brackets and BPA confirmed against Form 428.')
    cs_row[code] = r
    put(ws, r, 1, name, font=BOLD)
    put(ws, r, 2, code, align=CTR)
    put(ws, r, 3, bpa, font=INPUT, fmt=MONEY)
    put(ws, r, 4, rate, font=INPUT, fmt=PCT3)
    put(ws, r, 5, f'=C{r}*D{r}', fmt=MONEY2)
    put(ws, r, 6, sr1, font=INPUT, fmt=PCT1)
    put(ws, r, 7, st1, font=INPUT, fmt=MONEY, fill=GREENF if code == 'ON' else None)
    put(ws, r, 8, sr2, font=INPUT, fmt=PCT1)
    put(ws, r, 9, st2, font=INPUT, fmt=MONEY, fill=GREENF if code == 'ON' else None)
    put(ws, r, 10, OSC['t1'] if code == 'ON' else '', fmt=MONEY, fill=GREENF if code == 'ON' else None)
    put(ws, r, 11, OSC['t2'] if code == 'ON' else '', fmt=MONEY, fill=GREENF if code == 'ON' else None)
    put(ws, r, 12, note, font=SMALL, align=WRAP, fill=REDF if note.startswith('ERROR') else None)
    put(ws, r, 13, '', fill=BLUEF); put(ws, r, 14, '', fill=BLUEF)
    ws.row_dimensions[r].height = 52 if len(note) > 140 else 30
    r += 1
CS_END = r - 1

put(ws, r + 1, 1, 'Quebec federal abatement', font=BOLD, border=False)
put(ws, r + 1, 2, 0.165, font=INPUT, fmt=PCT1)
put(ws, r + 1, 3, 'Confirmed: 16.5% of basic federal tax, T4127 Table 8.2 and Form 5005-R line 44000. Applied to Quebec residents only.',
    font=SMALL, border=False)
ABATE_REF = f"'Credits and Surtax'!$B${r+1}"
r += 3
put(ws, r, 1, 'Ontario surtax — source text and cross-check', font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
put(ws, r, 1, OSC['src'], font=SMALL, align=WRAP, border=False); ws.row_dimensions[r].height = 30
r += 1
put(ws, r, 1, OSC['crosscheck'], font=SMALL, align=WRAP, border=False)
r += 1
put(ws, r, 1, 'Independently confirmed a second time in CRA payroll formulas T4127 Table 8.2, which lists the Ontario surtax '
              'V1 thresholds as $5,710 at 20% and $7,307 at 36%.', font=SMALL, align=WRAP, border=False)

r += 2
put(ws, r, 1, 'Ontario Health Premium 2025 — now implemented in the app (ON428 line 89)',
    font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
header(ws, r, ['Taxable income up to', 'Base premium', 'Plus, on excess over the previous band', '', '', '', '', '', '', '', '', '', '', ''])
r += 1
OHP_START = r
prev = 0
for upper, base, marg in V['ohp']:
    put(ws, r, 1, upper, fmt=MONEY)
    put(ws, r, 2, base, fmt=MONEY)
    put(ws, r, 3, marg, fmt=PCT1)
    prev = upper; r += 1
put(ws, r + 1, 1, 'The premium reaches $600 at $72,000 of taxable income and $750 from $72,600 up. The Tax Engine tab reads '
                  'this table directly, so editing it changes the calculation.', font=SMALLI, border=False)

# ══════════════════════════════════════════════════════════════════════════
# 5. TAX ENGINE  (live)
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Tax Engine', [16, 7, 14, 13, 13, 12, 14, 14, 13, 13, 12, 13, 14, 14, 11, 14], freeze='A7', tab='00B050')
title(ws, 'Tax Engine — live replication of the app\'s tax calculation (post-fix code)',
      'Change the income in the yellow cell; all 13 jurisdictions recompute from the Tax Brackets and Credits tabs. '
      'This reproduces the app\'s arithmetic exactly, including its rounding. Compare the Combined column against your own software.', 16)

put(ws, 4, 1, 'Annual income', font=BOLD, border=False)
put(ws, 4, 2, 100000, font=INPUT, fmt=MONEY, fill=YELLOW)
INC = "'Tax Engine'!$B$4"
put(ws, 4, 3, '<- change this', font=SMALLI, border=False)
put(ws, 5, 1, 'Note', font=BOLD, border=False)
put(ws, 5, 2, 'The app treats this figure as taxable income: no RRSP deduction, no CPP/EI, no employment amount, '
              'no income-tested credits. Tax shown is income tax only.', font=SMALLI, border=False)

BR = "'Tax Brackets'!"
CODE_R = f'{BR}$B${BRK_START}:$B${BRK_END}'
LOW_R  = f'{BR}$D${BRK_START}:$D${BRK_END}'
UPP_R  = f'{BR}$E${BRK_START}:$E${BRK_END}'
RATE_R = f'{BR}$F${BRK_START}:$F${BRK_END}'
CSC    = f"'Credits and Surtax'!$B${CS_START}:$B${CS_END}"
CSBPA  = f"'Credits and Surtax'!$E${CS_START}:$E${CS_END}"
CSR1   = f"'Credits and Surtax'!$F${CS_START}:$F${CS_END}"
CST1   = f"'Credits and Surtax'!$G${CS_START}:$G${CS_END}"
CSR2   = f"'Credits and Surtax'!$H${CS_START}:$H${CS_END}"
CST2   = f"'Credits and Surtax'!$I${CS_START}:$I${CS_END}"

def bracket_tax(code_expr):
    """SUMPRODUCT bracket arithmetic, elementwise-safe for LibreOffice."""
    return (f'SUMPRODUCT(({CODE_R}={code_expr})*({INC}>{LOW_R})*'
            f'((({UPP_R}<{INC})*{UPP_R})+(({UPP_R}>={INC})*{INC})-{LOW_R})*{RATE_R})')

OHP_U = f"'Credits and Surtax'!$A${OHP_START}:$A${OHP_START + len(V['ohp']) - 1}"
OHP_B = f"'Credits and Surtax'!$B${OHP_START}:$B${OHP_START + len(V['ohp']) - 1}"
OHP_M = f"'Credits and Surtax'!$C${OHP_START}:$C${OHP_START + len(V['ohp']) - 1}"
# band = first row whose upper bound exceeds the income; MATCH(...,1) finds the row below it
OHP_BAND = f'MATCH({INC},{OHP_U},1)+1'
OHP_F = (f'IF($B{{r}}<>"ON",0,IF({INC}<=20000,0,'
         f'INDEX({OHP_B},{OHP_BAND})+INDEX({OHP_M},{OHP_BAND})*({INC}-INDEX({OHP_U},{OHP_BAND}-1))))')

header(ws, 6, ['Jurisdiction', 'Code', 'Federal tax before credits', 'Federal BPA credit', 'Net federal tax',
               'QC abatement', 'FEDERAL PAYABLE', 'Prov. tax before credits', 'Prov. BPA credit', 'Net prov. tax',
               'Prov. surtax', 'Ontario Health Premium', 'PROVINCIAL PAYABLE', 'COMBINED TAX', 'Effective rate',
               'Your own software'])

TE_START = 7
r = TE_START
for code in PROV_ORDER:
    p = D['provinces'][code]
    put(ws, r, 1, p['name'], font=BOLD)
    put(ws, r, 2, code, align=CTR)
    put(ws, r, 3, f'={bracket_tax(chr(34) + "FED" + chr(34))}', fmt=MONEY2)
    put(ws, r, 4, f'=INDEX({CSBPA},MATCH("FED",{CSC},0))', fmt=MONEY2)
    put(ws, r, 5, f'=MAX(0,ROUND(C{r}-D{r},0))', fmt=MONEY)
    put(ws, r, 6, f'=IF($B{r}="QC",E{r}-ROUND(E{r}*(1-{ABATE_REF}),0),0)', fmt=MONEY)
    put(ws, r, 7, f'=E{r}-F{r}', font=BOLD, fmt=MONEY, fill=BLUEF)
    put(ws, r, 8, f'={bracket_tax(f"$B{r}")}', fmt=MONEY2)
    put(ws, r, 9, f'=INDEX({CSBPA},MATCH($B{r},{CSC},0))', fmt=MONEY2)
    put(ws, r, 10, f'=MAX(0,ROUND(H{r}-I{r},0))', fmt=MONEY)
    put(ws, r, 11, f'=MAX(0,J{r}-INDEX({CST1},MATCH($B{r},{CSC},0)))*INDEX({CSR1},MATCH($B{r},{CSC},0))'
                   f'+MAX(0,J{r}-INDEX({CST2},MATCH($B{r},{CSC},0)))*INDEX({CSR2},MATCH($B{r},{CSC},0))', fmt=MONEY2)
    put(ws, r, 12, '=' + OHP_F.format(r=r), fmt=MONEY)
    put(ws, r, 13, f'=ROUND(J{r}+K{r},0)+L{r}', font=BOLD, fmt=MONEY, fill=GREENF)
    put(ws, r, 14, f'=G{r}+M{r}', font=BOLD, fmt=MONEY, fill=AMBER)
    put(ws, r, 15, f'=IF({INC}>0,N{r}/{INC},0)', fmt=PCT1)
    put(ws, r, 16, '', fill=BLUEF)
    r += 1
TE_END = r - 1
put(ws, TE_END + 1, 16, '<- paste your own', font=SMALLI, border=False)
put(ws, TE_END + 2, 1,
    'Column P is for you: paste the total income tax your own software returns for the same income, so the two can be '
    'compared side by side. Note the app treats the income you enter as TAXABLE income and excludes CPP and EI, so set your '
    'software up the same way before comparing.',
    font=SMALLI, border=False)

# federal bracket-by-bracket trace
tr = TE_END + 4
put(ws, tr, 1, 'Federal calculation, band by band', font=Font(name=FONT, size=11, bold=True, color='1F3864'), border=False)
header(ws, tr + 1, ['Band', 'Rate', 'Lower', 'Upper', 'Income in band', 'Tax in band'] + [''] * 10)
r = tr + 2
for i, (upper, rate) in enumerate(D['fedBrackets'], 1):
    lower = 0 if i == 1 else D['fedBrackets'][i - 2][0]
    put(ws, r, 1, f'Band {i}', font=BOLD)
    put(ws, r, 2, rate, fmt=PCT3)
    put(ws, r, 3, lower, fmt=MONEY)
    put(ws, r, 4, upper, fmt=MONEY)
    put(ws, r, 5, f'=MAX(0,MIN({INC},D{r})-C{r})', fmt=MONEY)
    put(ws, r, 6, f'=E{r}*B{r}', fmt=MONEY2)
    r += 1
put(ws, r, 1, 'Basic federal tax', font=BOLD)
put(ws, r, 6, f'=SUM(F{tr+2}:F{r-1})', font=BOLD, fmt=MONEY2)
put(ws, r + 1, 1, 'Less BPA credit', font=BOLD)
put(ws, r + 1, 6, f'=-INDEX({CSBPA},MATCH("FED",{CSC},0))', fmt=MONEY2)
put(ws, r + 2, 1, 'Net federal tax', font=BOLD)
put(ws, r + 2, 6, f'=MAX(0,ROUND(F{r}+F{r+1},0))', font=BOLD, fmt=MONEY, fill=BLUEF)

# ══════════════════════════════════════════════════════════════════════════
# 6. FEDERAL ALLOCATION
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Federal Allocation', [5, 13, 27, 11, 52, 12, 13, 11, 13, 12, 60, 17, 15, 20, 34], freeze='A8', tab='2563EB')
title(ws, 'Federal spending allocation — the 20 categories, their coded shares, and what the accounts actually show',
      'Columns G-H test the coded share against the methodology\'s OWN cited dollars. Columns I-K test it against Public '
      'Accounts 2024-25 actuals on a single consistent denominator. Six categories fail by 1.5 points or more.', 15)

put(ws, 4, 1, 'Denominator', font=BOLD, border=False)
put(ws, 4, 2, 544, font=INPUT, fmt='$#,##0"B"', fill=YELLOW)
FDEN = "'Federal Allocation'!$B$4"
put(ws, 4, 3, FED['denominator']['verdict'], font=Font(name=FONT, size=10, bold=True, color='C00000'), border=False)
put(ws, 5, 3, FED['denominator']['note'], font=SMALL, align=WRAP, border=False)
ws.row_dimensions[5].height = 58
put(ws, 6, 3, 'Total federal expenses by year ($B, excl. / incl. net actuarial losses):  '
    + '   |   '.join(f"{y}: {a}/{b} ({s})" for y, a, b, s in FED['denominator']['table']),
    font=SMALL, align=WRAP, border=False)
ws.row_dimensions[6].height = 26

header(ws, 7, ['No.', 'Key', 'Category', 'Coded share', 'Line items cited by the methodology', 'Cited $B',
               'Implied share (cited $ / denominator)', 'Gap vs coded (pp)', 'VERIFIED share (2024-25 actuals)',
               'Coded error (pp)', 'Verification note', 'Fiscal year of cited $', 'Source cited',
               'Has provincial counterpart?'] + REVIEW_COLS)

CITED = {
    'cht':        (54.7, 'Canada Health Transfer $54.7B', '2025-26 (Budget 2025)', 'Budget 2025 / Finance Canada Major Transfers'),
    'health':     (11.0, 'Health Canada and PHAC operations, approx. $11B', 'not stated', 'Public Accounts 2023-24'),
    'cst':        (15.9, 'Canada Social Transfer $15.9B', '2025-26 (Budget 2025)', 'Budget 2025 / Finance Canada Major Transfers'),
    'socialEI':   (60.6, 'EI benefits approx. $33B + Canada Child Benefit approx. $27B (app text states $60.6B)', 'not stated', 'Public Accounts 2023-24 / Budget 2025'),
    'oas':        (83.1, 'Old Age Security $68.4B + GIS $14.7B', '2025-26 (Budget 2025 projection)', 'Budget 2025'),
    'debt':       (55.6, 'Public debt charges $55.6B', '2025-26 (Budget 2025 projection)', 'Budget 2025'),
    'admin':      (31.7, 'Equalization $21.9B + TFF $4.2B + other fiscal arrangements approx. $5.6B, plus unquantified departmental operations', 'mixed', 'Budget 2025 / Public Accounts'),
    'education':  (None, 'Canada Student Grants and Loans, federal research funding, official languages education transfers', 'not stated', 'not stated'),
    'transport':  (None, 'Infrastructure Canada, Transport Canada, Canada Community-Building Fund', 'not stated', 'not stated'),
    'indigenous': (None, 'Indigenous Services Canada, Crown-Indigenous Relations', 'not stated', 'not stated'),
    'justice':    (None, 'RCMP, federal corrections, courts, border services', 'not stated', 'not stated'),
    'defence':    (None, 'Department of National Defence, CAF operations', 'not stated', 'not stated'),
    'housing':    (None, 'National Housing Strategy, CMHC programs', 'not stated', 'not stated'),
    'environment':(None, 'Environment and Climate Change Canada, carbon pricing administration', 'not stated', 'not stated'),
    'science':    (None, 'Granting councils (NSERC, SSHRC, CIHR), NRC', 'not stated', 'not stated'),
    'intlDev':    (None, 'Global Affairs Canada official development assistance', 'not stated', 'not stated'),
    'immigration':(None, 'IRCC, settlement services', 'not stated', 'not stated'),
    'agriculture':(None, 'Agriculture and Agri-Food Canada, supply management', 'not stated', 'not stated'),
    'veterans':   (None, 'Veterans Affairs Canada benefits and services', 'not stated', 'not stated'),
    'other':      (None, 'Remaining departmental spending, contingencies, Crown corporations', 'not stated', 'not stated'),
}

FA_START = 8
r = FA_START
for i, cat in enumerate(D['cats'], 1):
    cited, items, fy, src = CITED[cat['key']]
    vshare, vnote = FED['verified_share'][cat['key']]
    put(ws, r, 1, i, align=CTR)
    put(ws, r, 2, cat['key'], font=SMALL)
    put(ws, r, 3, cat['label'], font=BOLD)
    put(ws, r, 4, cat['fedPct'] / 100, font=INPUT, fmt=PCT1)
    put(ws, r, 5, items, font=SMALL, align=WRAP)
    put(ws, r, 6, cited if cited is not None else '', font=INPUT, fmt='$#,##0.0"B"',
        fill=AMBER if cited is None else None)
    put(ws, r, 7, f'=IF(F{r}="","",F{r}/{FDEN})', fmt=PCT1)
    put(ws, r, 8, f'=IF(F{r}="","",(G{r}-D{r})*100)', fmt=PP)
    if vshare is not None:
        put(ws, r, 9, vshare / 100, fmt=PCT1, fill=GREENF)
        put(ws, r, 10, f'=(D{r}-I{r})*100', fmt=PP)
        big = abs(cat['fedPct'] - vshare) >= 1.5
        if big:
            ws.cell(r, 10).fill = REDF
            ws.cell(r, 4).fill = REDF
    else:
        put(ws, r, 9, '', fill=AMBER)
        put(ws, r, 10, '', fill=AMBER)
    put(ws, r, 11, vnote, font=SMALL, align=WRAP)
    put(ws, r, 12, fy, font=SMALL, align=WRAP, fill=AMBER if fy in ('not stated', 'mixed') else None)
    put(ws, r, 13, src, font=SMALL, align=WRAP, fill=AMBER if src == 'not stated' else None)
    put(ws, r, 14, 'Yes — stacked with provincial' if cat['provKey'] else 'No — federal only', font=SMALL, align=WRAP)
    put(ws, r, 15, '', fill=BLUEF); put(ws, r, 16, '', fill=BLUEF)
    ws.row_dimensions[r].height = max(30, 11 * (len(vnote) // 68 + 1))
    r += 1
FA_END = r - 1
put(ws, r, 3, 'TOTAL', font=BOLD, fill=GREY)
put(ws, r, 4, f'=SUM(D{FA_START}:D{FA_END})', font=BOLD, fmt=PCT1, fill=GREY)
put(ws, r, 5, 'Coded shares are forced to sum to exactly 100%.', font=SMALLI, fill=GREY)
put(ws, r, 6, f'=SUM(F{FA_START}:F{FA_END})', font=BOLD, fmt='$#,##0.0"B"', fill=GREY)
put(ws, r, 7, f'=IF({FDEN}>0,F{r}/{FDEN},"")', font=BOLD, fmt=PCT1, fill=GREY)
for c in (8, 9, 10, 11, 12, 13, 14, 15, 16): put(ws, r, c, '', fill=GREY)
r += 2

put(ws, r, 1, 'The structural problem behind the numbers', font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
put(ws, r, 1, FED['structural'], font=SMALL, align=WRAP, border=False)
ws.row_dimensions[r].height = 56
r += 2

put(ws, r, 1, 'Line items cited by the methodology, checked one by one',
    font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
header(ws, r, ['Cited figure', '', 'What the accounts show', '', '', '', '', '', '', '', 'Verdict', '', '', '', '', ''])
r += 1
LI_FILL = {'CORRECT': GREENF, 'ROUGHLY RIGHT': GREENF, 'COINCIDENTALLY RIGHT': AMBER, 'STALE': AMBER,
           'MIS-DATED': AMBER, 'WRONG': REDF, 'SPLIT UNSUPPORTED': REDF}
for claim, actual, verdict in FED['line_items']:
    put(ws, r, 1, claim, font=BOLD, align=WRAP)
    ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=10)
    c = ws.cell(r, 3, actual); c.font = SMALL; c.alignment = WRAP; c.border = BOX
    put(ws, r, 11, verdict, font=BOLD, align=WRAP, fill=LI_FILL.get(verdict, GREY))
    ws.row_dimensions[r].height = max(26, 11 * (len(actual) // 100 + 1))
    r += 1
r += 1
put(ws, r, 1, 'Note the last two rows: the app\'s Sources text ($31.7B) is RIGHT and the methodology document\'s component '
              'pair ($21.9B + $4.2B) is wrong — the opposite of how the discrepancy first appears. See F-28.',
    font=SMALLI, align=WRAP, border=False)
r += 2

B = FED['benchmark']
put(ws, r, 1, 'The benchmark a reviewer should rebuild this against',
    font=Font(name=FONT, size=11, bold=True, color='1F3864'), border=False)
r += 1
put(ws, r, 1, B['table'] + ' ' + B['note'], font=SMALL, align=WRAP, border=False)
ws.row_dimensions[r].height = 28
r += 1
put(ws, r, 1, B['url'], font=SMALL, border=False)
r += 2
header(ws, r, ['Federal CCOFOG function, reference year 2024', '', '$M', '', '', '', '', '', '', '', '', '', '', '', '', ''])
r += 1
BM_START = r
for name, val in B['values']:
    put(ws, r, 1, name, font=BOLD if name == 'TOTAL' else BASE, fill=GREY if name == 'TOTAL' else None)
    put(ws, r, 2, '', fill=GREY if name == 'TOTAL' else None)
    put(ws, r, 3, val, fmt='#,##0', font=BOLD if name == 'TOTAL' else BASE, fill=GREY if name == 'TOTAL' else None)
    r += 1
r += 1
put(ws, r, 1, B['caveats'], font=SMALL, align=WRAP, border=False)
ws.row_dimensions[r].height = 70

# ══════════════════════════════════════════════════════════════════════════
# 7. PROVINCIAL ALLOCATION
# ══════════════════════════════════════════════════════════════════════════
ncol = 3 + len(SPEND_KEYS) + 5
ws = sheet('Provincial Allocation', [16, 7] + [11] * len(SPEND_KEYS) + [10, 30, 15, 20, 34], freeze='C5', tab='2563EB')
title(ws, 'Provincial spending allocation — share of total provincial expenditure by function',
      'These 13 rows are the entirety of the provincial side of the app. Each row is forced to sum to 100% and every value is '
      'rounded to a whole percentage point. The app cites StatCan Table 10-10-0005-01 plus unspecified "individual provincial '
      'public accounts where StatCan data required interpretation" — which is not a reproducible derivation. See Finding F-11.', ncol)

header(ws, 4, ['Jurisdiction', 'Code'] + SPEND_LBL + ['TOTAL', 'Source cited', 'Vintage'] + REVIEW_COLS)
PA_START = 5
r = PA_START
pa_row = {}
for code in PROV_ORDER:
    p = D['provinces'][code]
    pa_row[code] = r
    put(ws, r, 1, p['name'], font=BOLD)
    put(ws, r, 2, code, align=CTR)
    for j, k in enumerate(SPEND_KEYS):
        put(ws, r, 3 + j, p['spending'][k] / 100, font=INPUT, fmt=PCT1)
    lastc = get_column_letter(2 + len(SPEND_KEYS))
    put(ws, r, 3 + len(SPEND_KEYS), f'=SUM(C{r}:{lastc}{r})', font=BOLD, fmt=PCT1, fill=GREENF)
    put(ws, r, 4 + len(SPEND_KEYS), 'StatCan 10-10-0005-01 (2023) + provincial public accounts 2023-24', font=SMALL, align=WRAP)
    put(ws, r, 5 + len(SPEND_KEYS), '2023', font=SMALL, align=CTR)
    put(ws, r, 6 + len(SPEND_KEYS), '', fill=BLUEF)
    put(ws, r, 7 + len(SPEND_KEYS), '', fill=BLUEF)
    r += 1
PA_END = r - 1
PA_HDR_ROW = 4
r += 1

S = V['statcan']
put(ws, r, 1, 'What the cited source actually is', font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False); r += 1
for lab, txt in [
    ('Table cited', 'Statistics Canada Table 10-10-0005-01, described by the app as "Government finance statistics, statement of operations and balance sheet".'),
    ('Its real title', S['actual_title'] + ' — so the table NUMBER is right for functional data, but the app cites it by the title of a different (economic-classification) table family. See F-16.'),
    ('The real problem', S['universe'] + ' See F-02.'),
    ('Provincial-only alternative', S['prov_only_table'] + ' See F-03.'),
    ('Vintage', S['latest_year'] + ' See F-15.'),
    ('Comparability', S['comparability'] + ' See F-18.'),
]:
    put(ws, r, 1, lab, font=BOLD, align=WRAP, border=False)
    put(ws, r, 3, txt, font=SMALL, align=WRAP, border=False)
    ws.row_dimensions[r].height = max(16, 11 * (len(txt) // 110 + 1))
    r += 1

r += 1
put(ws, r, 1, 'Coded shares checked against the provinces\' own 2023-24 public accounts',
    font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
put(ws, r, 1, 'Four jurisdictions were traced back to source. Every one has multiple categories out by 2 points or more. '
              'Categories marked UNVERIFIED have no comparable line in that province\'s accounts at all, which is itself a '
              'finding — it means the app\'s ten-category taxonomy cannot be reconciled to the source documents.',
    font=SMALLI, align=WRAP, border=False)
ws.row_dimensions[r].height = 28
r += 2
header(ws, r, ['Jurisdiction', 'Category', 'Coded', 'Actual (per public accounts)', 'Verdict', '', '', '', '', '', '',
               'Reviewer verdict', 'Reviewer comment', ''])
r += 1
VB_START = r
for code in ['ON', 'QC', 'AB', 'NS']:
    pa = V['prov_actuals'][code]
    first = r
    for key, coded, actual, verdict in pa['rows']:
        put(ws, r, 1, D['provinces'][code]['name'] if r == first else '', font=BOLD if r == first else BASE)
        put(ws, r, 2, SPEND_LBL[SPEND_KEYS.index(key)], font=BASE)
        put(ws, r, 3, coded / 100, fmt=PCT1)
        put(ws, r, 4, actual, font=SMALL, align=WRAP)
        bad = verdict.startswith(('OVERSTATED', 'WORST')) or ' pp' in verdict
        put(ws, r, 5, verdict, font=SMALL, align=WRAP,
            fill=REDF if bad else (AMBER if verdict.startswith(('UNVERIFIED', 'AMBIGUOUS', 'DEFINITION', 'EDITORIAL')) else GREENF))
        put(ws, r, 12, '', fill=BLUEF); put(ws, r, 13, '', fill=BLUEF)
        r += 1
    put(ws, first, 6, f"Total expense {pa['total']}", font=SMALL, align=WRAP)
    put(ws, first + 1, 6, pa['src'], font=SMALL, align=WRAP)
    r += 1

r += 1
put(ws, r, 1, 'The "Social assistance" category in particular', font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
put(ws, r, 1, V['social_ei']['note'], font=SMALL, align=WRAP, border=False); ws.row_dimensions[r].height = 26; r += 1
put(ws, r, 1, V['social_ei']['composition'], font=SMALL, align=WRAP, border=False); ws.row_dimensions[r].height = 40; r += 1

# ══════════════════════════════════════════════════════════════════════════
# 8. CHT ADJUSTMENT
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('CHT Adjustment', [16, 7, 14, 16, 12, 13, 14, 15, 13, 15, 56, 20, 34], freeze='A5', tab='ED7D31')
title(ws, 'The Canada Health Transfer double-counting adjustment',
      'The app subtracts each province\'s CHT share from its health percentage, then renormalises the remaining categories back '
      'to 100%. Columns C-D are the inputs stated in the app\'s code comments; columns G-J are the verified figures. '
      'Only British Columbia\'s CHT is right, and the three territories are wrongly coded as receiving none at all.', 13)

header(ws, 4, ['Jurisdiction', 'Code', 'CHT $M (as coded)', 'Total prov. expenditure $B', 'chtPct as coded',
               'chtPct recomputed from C/D', 'OFFICIAL CHT $M', 'Coded less official $M',
               'CORRECTED chtPct', 'Error in coded pct (pp)', 'Verification note'] + REVIEW_COLS)

CHT_INPUTS = {
    'AB': (5840, 62.1, 'CHT figure never stated: the code comment cites the NATIONAL envelope ($49.4B) instead of Alberta\'s '
                       'share, and $49.4B/$62.1B is 79.5%, not the 9.4% coded (F-29). The $62.1B denominator is an exact match '
                       'for Alberta\'s FY2021-22 total PROGRAM expense — two years stale and the wrong measure, since program '
                       'expense excludes debt servicing and pension provisions. FY2023-24 total expense is $70,447M (F-08).'),
    'BC': (6810, 82.0, 'The only CHT figure in the app that is correct.'),
    'MB': (1770, 20.0, 'Denominator given only as "approx. $20B" — no source.'),
    'NB': (1050, 11.3, ''),
    'NL': (680, 9.4, ''),
    'NS': (1320, 13.2, 'The $13.2B denominator matches no Nova Scotia expense figure in five years (actuals: $12.28B, $12.63B, '
                       '$13.71B, $15.47B, $16.38B). FY2023-24 is $16.38B, so the denominator is understated by 19.4%. Origin unexplained.'),
    'ON': (19000, 187.1, 'The $187.1B denominator is closest to StatCan reference year 2022 ($188.7B). Ontario\'s FY2023-24 '
                         'actual total expense is $206.6B.'),
    'PE': (220, 2.7, ''),
    'QC': (11200, 136.6, 'The $136.6B denominator matches no recent StatCan year. Quebec\'s FY2023-24 actual is $151.5B.'),
    'SK': (1540, 19.0, ''),
    'NT': (0, None, 'ERROR — coded as zero on the stated reasoning that territories get health funding via Territorial Formula '
                    'Financing instead. They receive BOTH. Finance Canada 2023-24: CHT $55M alongside TFF $1,611M. See F-06.'),
    'NU': (0, None, 'ERROR — as above. Finance Canada 2023-24: CHT $50M alongside TFF $1,971M. Finance Canada\'s letter to '
                    'Nunavut names its CHT and CST in one sentence and its TFF in the next, as distinct entitlements.'),
    'YT': (0, None, 'ERROR — as above. Finance Canada 2023-24: CHT $56M alongside TFF $1,252M.'),
}
CHT_START = 5
r = CHT_START
cht_row = {}
for code in PROV_ORDER:
    p = D['provinces'][code]
    chtm, den, note = CHT_INPUTS[code]
    official = V['cht_correct'][code]
    corrected = V['cht_pct_correct'][code]
    terr = code in ('NT', 'NU', 'YT')
    cht_row[code] = r
    put(ws, r, 1, p['name'], font=BOLD)
    put(ws, r, 2, code, align=CTR)
    put(ws, r, 3, chtm if code != 'AB' else '', font=INPUT, fmt='$#,##0"M"', fill=AMBER if code == 'AB' else None)
    put(ws, r, 4, den if den is not None else '', font=INPUT, fmt='$#,##0.0"B"', fill=AMBER if den is None else None)
    put(ws, r, 5, p['chtPct'] / 100, font=INPUT, fmt=PCT1, fill=REDF if terr else None)
    put(ws, r, 6, f'=IF(OR(C{r}="",D{r}=""),"",C{r}/1000/D{r})', fmt=PCT1)
    put(ws, r, 7, official, fmt='$#,##0"M"', fill=GREENF)
    put(ws, r, 8, f'=IF(C{r}="","",C{r}-G{r})', fmt='$#,##0;($#,##0);-')
    put(ws, r, 9, corrected / 100, fmt=PCT1, fill=GREENF)
    put(ws, r, 10, f'=(E{r}-I{r})*100', fmt=PP, fill=REDF if terr else None)
    put(ws, r, 11, note if note else 'CHT figure and denominator both differ from the verified values; see the corrected columns.',
        font=SMALL, align=WRAP, fill=REDF if note.startswith('ERROR') else (AMBER if note else None))
    put(ws, r, 12, '', fill=BLUEF); put(ws, r, 13, '', fill=BLUEF)
    ws.row_dimensions[r].height = 56 if len(note) > 160 else (34 if note else 16)
    r += 1
CHT_END = r - 1
put(ws, r, 1, 'National total', font=BOLD, fill=GREY)
put(ws, r, 2, '', fill=GREY)
put(ws, r, 3, f'=SUM(C{CHT_START}:C{CHT_END})', font=BOLD, fmt='$#,##0"M"', fill=GREY)
for c in (4, 5, 6): put(ws, r, c, '', fill=GREY)
put(ws, r, 7, f'=SUM(G{CHT_START}:G{CHT_END})', font=BOLD, fmt='$#,##0"M"', fill=GREY)
put(ws, r, 8, f'=C{r}-G{r}', font=BOLD, fmt='$#,##0;($#,##0);-', fill=GREY)
for c in (9, 10): put(ws, r, c, '', fill=GREY)
put(ws, r, 11, 'The coded national total is essentially right. What has happened is that the territories\' $161M has been '
               'redistributed across the ten provinces — so this is a structural error, not a set of typos. Replace the whole set.',
    font=SMALL, align=WRAP, fill=GREY)
ws.row_dimensions[r].height = 34
for c in (12, 13): put(ws, r, c, '', fill=GREY)
r += 2
put(ws, r, 1, 'Sources', font=BOLD, border=False)
put(ws, r, 3, V['cht_src'], font=SMALL, align=WRAP, border=False); r += 1
put(ws, r, 3, 'Corrected shares = official CHT / ' + V['cht_denominator_src'], font=SMALL, align=WRAP, border=False); r += 1
put(ws, r, 3, 'Two caveats to disclose if these are published: Quebec\'s CHT is published gross of the Quebec abatement, and '
              'Finance Canada does not publish a CHT-only slice of the abatement recovery. And the $2B health top-up is booked '
              'to 2022-23 on the transfers page but labelled 2023-24 in the news release — so Ontario can legitimately be cited '
              'as $19,266M, $19,214M or $19,990M depending on basis. The coded $19.0B is none of these.',
    font=SMALL, align=WRAP, border=False)
ws.row_dimensions[r].height = 44
r += 1

# demonstration of the redistribution effect
r += 2
put(ws, r, 1, 'What the adjustment actually does — worked demonstration, Ontario',
    font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
put(ws, r, 1, 'The stated intent is to REMOVE CHT-funded healthcare from the provincial column. But because the remaining '
              'categories are renormalised back to 100%, no dollars leave the provincial column — they are REDISTRIBUTED from '
              'health to every other category. A correction aimed at health silently inflates education, debt, justice and the '
              'rest by about 11% of their own value. See Finding F-06.', font=SMALLI, border=False)
ws.row_dimensions[r].height = 42
r += 2
DEMO_HDR = r
header(ws, r, ['Category', 'Raw share', 'After CHT subtraction', 'Renormalised share', 'Change vs raw (pp)',
               'Relative change', '', '', '', '', '', ''])
r += 1
DEMO_START = r
on = D['provinces']['ON']
for k, lbl in zip(SPEND_KEYS, SPEND_LBL):
    put(ws, r, 1, lbl, font=BOLD)
    put(ws, r, 2, on['spending'][k] / 100, fmt=PCT1)
    put(ws, r, 3, (f'=MAX(0,B{r}-$E${cht_row["ON"]})' if k == 'health' else f'=B{r}'), fmt=PCT1)
    r += 1
DEMO_END = r - 1
put(ws, r, 1, 'Sum', font=BOLD, fill=GREY)
put(ws, r, 2, f'=SUM(B{DEMO_START}:B{DEMO_END})', font=BOLD, fmt=PCT1, fill=GREY)
put(ws, r, 3, f'=SUM(C{DEMO_START}:C{DEMO_END})', font=BOLD, fmt=PCT1, fill=GREY)
DEMO_SUM = r
for rr in range(DEMO_START, DEMO_END + 1):
    put(ws, rr, 4, f'=IF($C${DEMO_SUM}>0,C{rr}/$C${DEMO_SUM},0)', fmt=PCT1)
    put(ws, rr, 5, f'=(D{rr}-B{rr})*100', fmt=PP)
    put(ws, rr, 6, f'=IF(B{rr}>0,D{rr}/B{rr}-1,"")', fmt=PCT1)
put(ws, DEMO_SUM, 4, f'=SUM(D{DEMO_START}:D{DEMO_END})', font=BOLD, fmt=PCT1, fill=GREY)
for c in (5, 6): put(ws, DEMO_SUM, c, '', fill=GREY)
r = DEMO_SUM + 2
put(ws, r, 1, 'Read column F: health falls, and every other category rises by the same relative amount. '
              'The provincial total is unchanged at 100%.', font=SMALLI, border=False)
r += 2
for txt in [
    'Further questions for the reviewer:',
    'a. CHT is corrected for; the Canada Social Transfer, Equalization and Territorial Formula Financing are not. Those are '
    'larger in aggregate. For New Brunswick, Equalization alone is roughly a fifth of total spending, against a CHT share of 9.3%. '
    'Is a partial correction better or worse than none?',
    'b. The adjustment assumes CHT dollars are spent exclusively on health and that all other categories are funded entirely '
    'from provincial own-source revenue. Neither holds.',
    'c. The federal column values CHT at $54.7B while the provincial adjustment uses the 2023-24 figure of about $49.4B. '
    'One calculation, two vintages of the same transfer.',
]:
    put(ws, r, 1, txt, font=SMALLI, border=False); r += 1

# ══════════════════════════════════════════════════════════════════════════
# 9. ALLOCATION ENGINE (live)
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Allocation Engine', [5, 13, 27, 11, 13, 12, 12, 13, 13, 13, 13, 11], freeze='A9', tab='00B050')
title(ws, 'Allocation Engine — live replication of the app\'s spending split',
      'Set the income and province below. This reproduces exactly what the app prints in its Detailed Breakdown table, '
      'including the CHT adjustment and the app\'s per-row rounding.', 12)

put(ws, 4, 1, 'Income', font=BOLD, border=False)
put(ws, 4, 2, f'={INC}', font=LINKF, fmt=MONEY)
put(ws, 4, 3, 'linked to the Tax Engine tab', font=SMALLI, border=False)
put(ws, 5, 1, 'Province', font=BOLD, border=False)
put(ws, 5, 2, 'ON', font=INPUT, fill=YELLOW, align=CTR)
AE_PROV = "'Allocation Engine'!$B$5"
put(ws, 5, 3, '<- two-letter code: AB BC MB NB NL NS NT NU ON PE QC SK YT', font=SMALLI, border=False)

TEC = f"'Tax Engine'!$B${TE_START}:$B${TE_END}"
put(ws, 6, 1, 'Federal tax', font=BOLD, border=False)
put(ws, 6, 2, f"=INDEX('Tax Engine'!$G${TE_START}:$G${TE_END},MATCH({AE_PROV},{TEC},0))", font=LINKF, fmt=MONEY)
put(ws, 7, 1, 'Provincial tax', font=BOLD, border=False)
put(ws, 7, 2, f"=INDEX('Tax Engine'!$M${TE_START}:$M${TE_END},MATCH({AE_PROV},{TEC},0))", font=LINKF, fmt=MONEY)
FEDT, PROVT = "'Allocation Engine'!$B$6", "'Allocation Engine'!$B$7"
put(ws, 6, 3, 'from the Tax Engine tab', font=SMALLI, border=False)
put(ws, 7, 3, 'from the Tax Engine tab', font=SMALLI, border=False)

header(ws, 8, ['No.', 'Key', 'Category', 'Federal share', 'Federal $', 'Raw prov. share', 'Adj. prov. share',
               'Renorm. prov. share', 'Provincial $', 'Combined $', '% of total tax', 'Federal only?'])

PA_CODE_R = f"'Provincial Allocation'!$B${PA_START}:$B${PA_END}"
CHT_CODE_R = f"'CHT Adjustment'!$B${CHT_START}:$B${CHT_END}"
CHT_PCT_R  = f"'CHT Adjustment'!$E${CHT_START}:$E${CHT_END}"

AE_START = 9
r = AE_START
health_row = None
for i, cat in enumerate(D['cats'], 1):
    put(ws, r, 1, i, align=CTR)
    put(ws, r, 2, cat['key'], font=SMALL)
    put(ws, r, 3, cat['label'], font=BOLD)
    put(ws, r, 4, f"=INDEX('Federal Allocation'!$D${FA_START}:$D${FA_END},MATCH($B{r},'Federal Allocation'!$B${FA_START}:$B${FA_END},0))", fmt=PCT1)
    put(ws, r, 5, f'=ROUND(D{r}*{FEDT},0)', fmt=MONEY)
    if cat['provKey']:
        col = get_column_letter(3 + SPEND_KEYS.index(cat['provKey']))
        put(ws, r, 6, f"=INDEX('Provincial Allocation'!${col}${PA_START}:${col}${PA_END},MATCH({AE_PROV},{PA_CODE_R},0))", fmt=PCT1)
        if cat['key'] == 'health':
            health_row = r
            put(ws, r, 7, f'=MAX(0,F{r}-INDEX({CHT_PCT_R},MATCH({AE_PROV},{CHT_CODE_R},0)))', fmt=PCT1, fill=AMBER)
        else:
            put(ws, r, 7, f'=F{r}', fmt=PCT1)
    else:
        put(ws, r, 6, 0, fmt=PCT1, fill=GREY)
        put(ws, r, 7, 0, fmt=PCT1, fill=GREY)
    put(ws, r, 12, 'federal only' if not cat['provKey'] else '', font=SMALL, align=CTR)
    r += 1
AE_END = r - 1
TOTADJ = f'$G${r}'
put(ws, r, 3, 'Sum of adjusted provincial shares', font=BOLD, fill=GREY)
put(ws, r, 4, '', fill=GREY)
put(ws, r, 5, f'=SUM(E{AE_START}:E{AE_END})', font=BOLD, fmt=MONEY, fill=GREY)
put(ws, r, 6, f'=SUM(F{AE_START}:F{AE_END})', font=BOLD, fmt=PCT1, fill=GREY)
put(ws, r, 7, f'=SUM(G{AE_START}:G{AE_END})', font=BOLD, fmt=PCT1, fill=AMBER)
SUMROW = r
for rr in range(AE_START, AE_END + 1):
    put(ws, rr, 8, f'=IF(AND({TOTADJ}>0,G{rr}>0),G{rr}/{TOTADJ},0)', fmt=PCT1)
    put(ws, rr, 9, f'=IF(AND({TOTADJ}>0,G{rr}>0),ROUND(H{rr}*{PROVT},0),0)', fmt=MONEY)
    put(ws, rr, 10, f'=E{rr}+I{rr}', font=BOLD, fmt=MONEY)
    put(ws, rr, 11, f'=IF(({FEDT}+{PROVT})>0,J{rr}/({FEDT}+{PROVT}),0)', fmt=PCT1)
put(ws, SUMROW, 8, f'=SUM(H{AE_START}:H{AE_END})', font=BOLD, fmt=PCT1, fill=GREY)
put(ws, SUMROW, 9, f'=SUM(I{AE_START}:I{AE_END})', font=BOLD, fmt=MONEY, fill=GREY)
put(ws, SUMROW, 10, f'=SUM(J{AE_START}:J{AE_END})', font=BOLD, fmt=MONEY, fill=GREY)
put(ws, SUMROW, 11, f'=SUM(K{AE_START}:K{AE_END})', font=BOLD, fmt=PCT1, fill=GREY)
put(ws, SUMROW, 12, '', fill=GREY)

r = SUMROW + 2
put(ws, r, 1, 'Footing check — the app\'s own table does not foot', font=Font(name=FONT, size=11, bold=True, color='C00000'), border=False)
r += 1
for lab, f1, f2 in [
    ('Sum of the Federal $ column', f'=E{SUMROW}', f'={FEDT}'),
    ('Sum of the Provincial $ column', f'=I{SUMROW}', f'={PROVT}'),
    ('Sum of the "% of total tax" column', f'=K{SUMROW}', '=1'),
]:
    put(ws, r, 1, lab, font=BASE, border=False)
    put(ws, r, 4, f1, fmt=MONEY if '%' not in lab else PCT1)
    put(ws, r, 5, f2, fmt=MONEY if '%' not in lab else PCT1)
    put(ws, r, 6, f'=D{r}-E{r}', fmt='$#,##0;($#,##0);-' if '%' not in lab else '0.000%', fill=AMBER)
    put(ws, r, 7, 'difference', font=SMALLI, border=False)
    r += 1
put(ws, r + 1, 1, 'Each row is rounded to the dollar independently, so the columns can miss the stated total by a few dollars '
                  'while the app prints a Total row that shows the exact figure. Cosmetic, but an auditor will notice. See Finding F-12.',
    font=SMALLI, border=False)

# ══════════════════════════════════════════════════════════════════════════
# 10. SOURCES
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Sources', [28, 46, 15, 30, 22, 20, 34], freeze='A4', tab='7F7F7F')
title(ws, 'Sources cited by the app and its methodology document',
      'The right-hand columns record whether a third party could actually reproduce the figure from the source as cited.', 7)
header(ws, 3, ['Used for', 'Source as cited', 'Vintage', 'URL', 'Reproducible as cited?'] + REVIEW_COLS)

SOURCES = [
    ('Federal tax brackets', 'Canada Revenue Agency, Canadian income tax rates for individuals', '2025',
     'https://www.canada.ca/en/revenue-agency/services/tax/individuals/tax-rates-brackets/last-year.html',
     'YES — and verified correct. Caution: CRA\'s summary page carries the wrong Manitoba thresholds. Prefer the Form 428s.'),
    ('Provincial tax brackets', 'TaxTips.ca 2025 provincial rates', '2025', 'https://www.taxtips.ca/',
     'YES — and verified correct for all 13, except that Yukon has been transcribed with an extra bracket. TaxTips is a '
     'secondary source; the filed CRA Form 428s are the primary one and should be cited instead for a published tool.'),
    ('Federal spending actuals', 'Public Accounts of Canada 2023-24, Volume I', 'FY ended 31 Mar 2024',
     'https://www.tpsgc-pwgsc.gc.ca/recgen/cpc-pac/2024/vol1/s3/charges-expenses-eng.html',
     'NO — the app\'s $544B denominator is not in this document. 2023-24 total expenses were $521.4B including net actuarial '
     'losses, $513.9B excluding them. $544B is the 2024-25 figure. See F-11.'),
    ('Federal spending projections', 'Federal Budget 2025', '2025-26 projections', 'https://budget.canada.ca/2025/report-rapport/anx1-en.html',
     'Partly — the document exists and several line items do come from it, but the app never says which figure comes from '
     'which document. Budget 2025 has also been superseded on the fiscal outlook by the Spring Economic Update 2026.'),
    ('Federal spending benchmark (recommended)', 'Statistics Canada Table 10-10-0024-01, federal government component',
     '2024', 'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1010002401',
     'NOT CURRENTLY USED — this is the table the federal split should be rebuilt on. It is the only official federal-only '
     'table splitting all spending across exhaustive, non-overlapping COFOG functions.'),
    ('Provincial spending shares', 'Statistics Canada Table 10-10-0005-01, cited as "Government finance statistics, statement '
     'of operations and balance sheet"', '2023',
     'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1010000501',
     'NO — three separate problems. The title is wrong (it is the CCOFOG functional table). Its only sub-national component '
     'is provincial-territorial AND LOCAL government, so it includes municipalities, school boards, hospitals and '
     'universities. And it has no federal row at all. See F-02, F-16.'),
    ('Provincial spending shares (supplement)', '"Individual provincial public accounts 2023-24, where StatCan data required interpretation"',
     '2023-24', 'not given',
     'NO — no documents named, no interpretation rules stated. A reviewer cannot reproduce any provincial row from this.'),
    ('CHT by province', 'Finance Canada per-capita CHT data (referenced only in code comments)', '2023-24',
     'https://www.canada.ca/en/department-finance/programs/federal-transfers/major-federal-transfers.html',
     'The source exists and is authoritative, but the app does not link it and the figures do not match it — only BC\'s is '
     'right, and the territories are wrongly given zero. See F-06, F-07.'),
    ('Provincial expenditure denominators', 'Not identified — dollar figures appear only in code comments', '2022-23 per comments', 'not given',
     'NO — the denominators driving the entire CHT adjustment have no cited source, and at least two of them (Alberta, Nova '
     'Scotia) do not correspond to any published total expense figure. See F-08.'),
]
r = 4
for a, b, c, d, e in SOURCES:
    put(ws, r, 1, a, font=BOLD, align=WRAP)
    put(ws, r, 2, b, font=BASE, align=WRAP)
    put(ws, r, 3, c, font=SMALL, align=CTR)
    put(ws, r, 4, d, font=SMALL, align=WRAP)
    put(ws, r, 5, e, font=SMALL, align=WRAP, fill=REDF if e.startswith('NO') else (AMBER if e.startswith('Partly') else GREENF))
    put(ws, r, 6, '', fill=BLUEF); put(ws, r, 7, '', fill=BLUEF)
    ws.row_dimensions[r].height = 46
    r += 1

# ══════════════════════════════════════════════════════════════════════════
# 11. PROVINCIAL SOURCES  (data-source research for the allocation half)
# ══════════════════════════════════════════════════════════════════════════
PS = json.load(open(os.path.join(HERE, 'provsources.json')))

ws = sheet('Provincial Sources', [46, 34, 40, 20, 26, 30, 74, 20, 34], freeze='A4', tab='7030A0')
title(ws, 'Provincial spending — candidate data sources and what each can actually deliver',
      'The allocation half has no equivalent of a CRA form to check against: you must choose a universe and a taxonomy, and '
      'each choice costs something. Every claim below was verified against the downloaded source files, not taken from '
      'documentation. Figures are 2024, $ millions, unless stated. Relates to F-01, F-02, F-03, F-16, F-18 and F-19.', 9)
header(ws, 3, ['Source', 'Universe', 'Classification', 'Coverage', 'Can it produce the split?',
               'Verdict', 'Notes'] + REVIEW_COLS)

VF = {'CORE SOURCE': GREENF, 'CITED BY APP — WRONG UNIVERSE': REDF, 'DISCONTINUED 2009': AMBER,
      'BEST NON-STATCAN SOURCE, BUT CANNOT SPLIT': AMBER, 'BEST CHECK ON THE HEALTH ROW': GREENF,
      'DEBT ROW AND RECONCILIATION ONLY': GREY, 'FINDING AID ONLY': GREY,
      'NOT USABLE FOR THE SPLIT': GREY}
r = 4
for c in PS['candidates']:
    cell = put(ws, r, 1, c['src'], font=BOLD, align=WRAP)
    cell.hyperlink = c['url']; cell.font = Font(name=FONT, size=10, bold=True, color='0563C1', underline='single')
    put(ws, r, 2, c['universe'], font=SMALL, align=WRAP)
    put(ws, r, 3, c['classif'], font=SMALL, align=WRAP)
    put(ws, r, 4, c['cover'], font=SMALL, align=WRAP)
    put(ws, r, 5, c['split'], font=BOLD, align=WRAP,
        fill=REDF if c['split'].startswith(('No', 'NO')) else (AMBER if c['split'].startswith('Partly') else GREENF))
    put(ws, r, 6, c['verdict'], font=BOLD, align=WRAP, fill=VF.get(c['verdict'], GREY))
    put(ws, r, 7, c['note'], font=SMALL, align=WRAP)
    put(ws, r, 8, '', fill=BLUEF); put(ws, r, 9, '', fill=BLUEF)
    ws.row_dimensions[r].height = max(60, 10 * (len(c['note']) // 72 + 1))
    r += 1


def ps_section(r, heading, blurb, cols):
    """Sub-table heading + column header. Returns the first data row."""
    r += 2
    put(ws, r, 1, heading, font=Font(name=FONT, size=11, bold=True, color='7030A0'), border=False)
    ws.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=9)
    c = ws.cell(r + 1, 1, blurb); c.font = SMALLI; c.alignment = WRAP
    ws.row_dimensions[r + 1].height = max(26, 11 * (len(blurb) // 118 + 1))
    header(ws, r + 2, cols + [''] * (9 - len(cols)))
    return r + 3


# ── A. debt carve-out ─────────────────────────────────────────────────────
r = ps_section(r, 'A. Debt carve-out from General public services — WORKS',
   'CCOFOG footnote 6: division 701 contains ALL debt interest regardless of the function the debt was incurred for. '
   'Interest expense comes from 10-10-0017-01, which is the same universe, agency and vintage as 10-10-0024-01 — so this '
   'is a same-basis subtraction, the only one available. Tested across every province-year 2015-2024: interest never '
   'exceeds division 701, so the residual is always positive. Columns D and E are live formulas.',
   ['Province', '701 General public services', 'Interest expense (10-10-0017-01)',
    'Residual = 701 - interest', 'Interest as % of 701'])
first = r
for prov, gps, interest in PS['debt']:
    put(ws, r, 1, prov, font=BOLD)
    put(ws, r, 2, gps, fmt=MONEY)
    put(ws, r, 3, interest, fmt=MONEY)
    put(ws, r, 4, f'=B{r}-C{r}', fmt=MONEY, fill=GREENF)
    put(ws, r, 5, f'=C{r}/B{r}', fmt=PCT1)
    r += 1
put(ws, r, 1, 'Assertion for the code', font=BOLD, fill=YELLOW)
put(ws, r, 2, f'=IF(MIN(D{first}:D{r-1})>0,"PASS - residual positive in all 13","FAIL")',
    font=BOLD, fill=YELLOW)
r += 1

# ── B. transport ──────────────────────────────────────────────────────────
r = ps_section(r, 'B. Transport carve-out by subtraction — DOES NOT WORK',
   'The available derivation is PTLG transport [7045] minus municipal transport [7045]. It looks safe: school boards, '
   'universities and health institutions have exactly ZERO Economic affairs in all 221 province-years, so nothing else is '
   'in the way, and the residual is positive everywhere and smaller than its parent. It fails because PTLG (10-10-0005-01) '
   'is CONSOLIDATED and the municipal figure (10-10-0024-01) is not — see section C for the size of that gap.',
   ['Province', 'PTLG transport [7045] (consolidated)', 'Municipal transport [7045] (unconsolidated)',
    'Residual', 'P&T Economic affairs [704]', 'Residual as % of parent'])
for prov, ptlg, muni, parent in PS['transport']:
    put(ws, r, 1, prov, font=BOLD)
    put(ws, r, 2, ptlg, fmt=MONEY)
    put(ws, r, 3, muni, fmt=MONEY)
    put(ws, r, 4, f'=B{r}-C{r}', fmt=MONEY, fill=AMBER)
    put(ws, r, 5, parent, fmt=MONEY)
    put(ws, r, 6, f'=D{r}/E{r}', fmt=PCT1)
    r += 1

# ── C. consolidation elimination ──────────────────────────────────────────
r = ps_section(r, 'C. Why section B fails — the size of the consolidation elimination',
   'Economic affairs [704], the parent of transport. If the two tables were on the same basis, the unconsolidated '
   'components would sum to the consolidated total. They do not, and the gap is material. In FIVE jurisdictions the '
   'provincial figure ALONE exceeds the consolidated PTLG total (shown in red). So the section B residual is not '
   'provincial transport spending — it is transport spending net of provincial-to-municipal transfers, which drops exactly '
   'the provincial transit money an urban reader cares most about.',
   ['Province', 'PTLG [704] consolidated', 'P&T [704]', 'Municipal [704]',
    'Sum of unconsolidated', 'Elimination', 'Elimination as % of consolidated'])
for prov, ptlg, pt, muni in PS['consol']:
    put(ws, r, 1, prov, font=BOLD)
    put(ws, r, 2, ptlg, fmt=MONEY)
    put(ws, r, 3, pt, fmt=MONEY, fill=REDF if pt > ptlg else None)
    put(ws, r, 4, muni, fmt=MONEY)
    put(ws, r, 5, f'=C{r}+D{r}', fmt=MONEY)
    put(ws, r, 6, f'=E{r}-B{r}', fmt=MONEY)
    put(ws, r, 7, f'=F{r}/B{r}', fmt=PCT1)
    r += 1
put(ws, r, 1, 'The reassuring test that does NOT transfer', font=BOLD, fill=YELLOW)
ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
c = ws.cell(r, 2, 'For functions only municipalities perform, PTLG and municipal agree within ~1% (ON fire protection '
    '2,631 vs 2,599; street lighting 188 vs 189; waste water 2,252 vs 2,259). That looks like proof the bases match. It is '
    'not: provinces barely fund those functions, so there is nothing to eliminate. Transport is the opposite case.')
c.font = SMALL; c.alignment = WRAP; c.fill = YELLOW
ws.row_dimensions[r].height = 34
r += 1

# ── D. reconciliation ─────────────────────────────────────────────────────
r = ps_section(r, 'D. The two core tables reconcile exactly from 2015',
   'CCOFOG footnote 2: the classification excludes acquisitions of non-financial assets and consumption of fixed capital, '
   'because integration with the macroeconomic accounts is still in progress. That predicts the identity below, and it '
   'holds to rounding in 130 of 130 province-years for 2015-2024 (max deviation $2M, 0.10% of expense). Before 2015 it does '
   'not: 2008-2014 deviates by up to $993M, or 7.08%. A derivation that mixes these two tables is therefore legitimate '
   'from 2015 and not before — which caps how far back the app can go.',
   ['Province', 'Sum of CCOFOG divisions', 'Expense (10-10-0017-01)', 'Consumption of fixed capital',
    'Expense - CFC', 'Residual (should be ~0)'])
for prov, cofog, expense, cfc in PS['recon']:
    put(ws, r, 1, prov, font=BOLD)
    put(ws, r, 2, cofog, fmt=MONEY)
    put(ws, r, 3, expense, fmt=MONEY)
    put(ws, r, 4, cfc, fmt=MONEY)
    put(ws, r, 5, f'=C{r}-D{r}', fmt=MONEY)
    put(ws, r, 6, f'=B{r}-E{r}', fmt=MONEY, fill=GREENF)
    r += 1

# ── E. FON cross-check ────────────────────────────────────────────────────
r = ps_section(r, 'E. Finances of the Nation as an independent measure of the debt row',
   'FON is Public Accounts basis and StatCan is CGFS basis, so the two are NOT interchangeable — total expenditure differs '
   'by 2-16%. What they give you is a bracket around the debt row. For Ontario: 5.5% (Ontario Public Accounts), 7.16% '
   '(FON), 7.41% (StatCan CCOFOG). The app codes 9%, which no measure supports. FON is the only source found that spans '
   'the 2009 FMS/CCOFOG discontinuity, so it is also the way to test whether a long-run series is stable.',
   ['Province', 'FON total expenditure', 'StatCan expense', 'FON / StatCan',
    'FON debt charges', 'StatCan interest', 'Difference', 'Difference %'])
for prov, ftot, stot, fdebt, sint in PS['fon']:
    put(ws, r, 1, prov, font=BOLD)
    put(ws, r, 2, ftot, fmt=MONEY)
    put(ws, r, 3, stot, fmt=MONEY)
    put(ws, r, 4, f'=B{r}/C{r}', fmt='0.000')
    put(ws, r, 5, fdebt, fmt=MONEY)
    put(ws, r, 6, sint, fmt=MONEY)
    put(ws, r, 7, f'=E{r}-F{r}', fmt=MONEY)
    put(ws, r, 8, f'=G{r}/F{r}', fmt=PCT1)
    r += 1

# ── F. the recommendation ─────────────────────────────────────────────────
r += 2
put(ws, r, 1, 'F. The most defensible construction found — and what it costs',
    font=Font(name=FONT, size=11, bold=True, color='7030A0'), border=False)
r += 1
REC = [
 ('Build', '10 CCOFOG divisions from the Provincial and territorial governments component of 10-10-0024-01, '
           'PLUS debt carved out of General public services using Interest expense from 10-10-0017-01. Eleven rows, two '
           'tables, one vintage, one universe, fully reproducible.', GREENF),
 ('Cost — no transport row', 'Transport cannot be carved out (section B). It can only appear as an annotation on Economic '
           'affairs, not as a row inside the 100%.', AMBER),
 ('Cost — 2015 onward only', 'The two tables do not reconcile before 2015 (section D).', AMBER),
 ('Cost — operating view only', 'CCOFOG excludes capital acquisition and consumption of fixed capital (footnote 2), so this '
           'is an operating-expense view and should be labelled as one.', AMBER),
 ('Cost — comparability', 'Footnote 4 advises against comparing provinces on a single component. The app invites exactly '
           'that comparison. Either drop the comparison, or accept the consolidated PTLG universe and stop claiming the '
           'tool answers "where does my PROVINCIAL tax go". This is the central product decision and it is not ours.', REDF),
 ('Open question for reviewers', 'Is an operating-expense, provincial-government-only, explicitly non-comparable view the '
           'right answer for a public tool — or is the comparable PTLG view with honest relabelling better journalism, even '
           'though it no longer answers the literal question the tool poses?', BLUEF),
]
for lab, txt, fill in REC:
    put(ws, r, 1, lab, font=BOLD, align=WRAP, fill=fill)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
    c = ws.cell(r, 2, txt); c.font = BASE; c.alignment = WRAP; c.border = BOX; c.fill = fill
    ws.row_dimensions[r].height = max(28, 12 * (len(txt) // 128 + 1))
    r += 1

# ══════════════════════════════════════════════════════════════════════════
# 12. VERIFICATION LOG
# ══════════════════════════════════════════════════════════════════════════
ws = sheet('Verification Log', [26, 16, 60, 52, 20, 34], freeze='A4', tab='548235')
title(ws, 'Verification log — what was checked against a primary source, and what was not',
      'Everything in this workbook that carries a verdict was checked in the course of this review. Items marked NOT CHECKED '
      'are where a third party is most needed. Note that canada.ca refuses automated requests, so CRA pages were read in a '
      'browser rather than fetched programmatically — the URLs all resolve normally.', 6)
header(ws, 3, ['Item', 'Verdict', 'What was found', 'Source'] + REVIEW_COLS)

LOG = [
 ('Federal brackets 2025', 'CORRECT', 'All five thresholds and rates confirmed. The 14.5% first-bracket rate is the correct '
  'full-year blend after the 15%-to-14% cut took effect 1 July 2025.', V['tax_verdicts']['FED']['src']),
 ('Federal BPA and credit rate', 'CORRECT', 'BPA $16,129 and the phase-down floor of $14,538 confirmed. The rate at which 2025 '
  'non-refundable credits are valued is 14.5% — T1 line 114 states it explicitly. The app\'s approach of valuing the BPA credit '
  'at the lowest bracket rate is therefore right for 2025, and will need changing to 14% for 2026.',
  'CRA T1 2025, line 114 / line 30000'),
 ('Quebec federal abatement', 'CORRECT', '16.5% of basic federal tax, confirmed on Form 5005-R line 44000 and in CRA payroll '
  'formulas T4127 Table 8.2.', 'https://www.canada.ca/en/revenue-agency/services/forms-publications/tax-packages-years/general-income-tax-benefit-package/5005-r.html'),
 ('All 13 provincial/territorial bracket schedules', 'CORRECT except Yukon', 'Every threshold, rate and basic personal amount '
  'checked against that jurisdiction\'s 2025 Form 428, and Revenu Quebec for Quebec. Yukon is the only schedule that is wrong.',
  'CRA Forms 5001-C through 5014-C; Revenu Quebec TP-1'),
 ('Yukon 2025 schedule', 'WRONG', 'Form YT428 has five brackets, not six. The coded 12.93% is an effective rate with the federal '
  'BPA clawback embedded: 12.8% + (1,591/75,532 x 6.4%) = 12.9348%. Arithmetic reproduced independently.',
  V['tax_verdicts']['YT']['src']),
 ('Ontario surtax thresholds', 'WRONG', 'Correct 2025 thresholds are 20% over $5,710 and 36% over $7,307. Confirmed twice: '
  'Form ON428 lines 66-68, and CRA payroll formulas T4127 Table 8.2. Cross-checked by indexing the 2024 thresholds ($5,554 / '
  '$7,108) by Ontario\'s 2.8% factor, which reproduces $5,710 / $7,307 exactly.', V['tax_verdicts']['ON']['src']),
 ('Surtaxes in other jurisdictions', 'NONE EXIST', 'All twelve other 2025 Form 428s were searched for "surtax". Ontario is the '
  'only jurisdiction with a personal income tax surtax in 2025. PEI\'s is confirmed eliminated for 2024 and later.',
  'CRA Forms 428, 2025'),
 ('Manitoba thresholds', 'CORRECT — do not change', 'CRA\'s own 2025 summary page wrongly lists the 2026 figures. Manitoba '
  'paused indexation effective 2025. The app is right and that CRA page is wrong.', V['tax_verdicts']['MB']['src']),
 ('Nova Scotia BPA', 'CORRECT — do not change', 'NS does not phase out its BPA in 2025. Budget 2025 replaced the old '
  'base-plus-supplement structure with a flat $11,744 for all filers.', V['tax_verdicts']['NS']['src']),
 ('Ontario Health Premium', 'MISSING FROM APP', 'Confirmed as Ontario income tax collected on Form ON428 line 89, flowing to '
  'T1 line 42800. Reaches $900. Full schedule reproduced on the Credits and Surtax tab.', 'CRA Form ON428 (5006-C), line 89'),
 ('StatCan Table 10-10-0005-01 identity', 'CITED WRONGLY', 'Real title is "Canadian Classification of Functions of Government '
  '(CCOFOG) by consolidated government component". It IS a functional table, so the number is right — but its only sub-national '
  'component is provincial-territorial AND LOCAL governments, which includes municipalities, school boards, hospitals and '
  'universities.', S['urls']['10100005']),
 ('Provincial-only COFOG availability', 'CONSTRAINED', 'Table 10-10-0024-01 has a provincial-and-territorial component but '
  'publishes only the ten top-level COFOG divisions. Debt-interest and transport are not obtainable at that level.',
  S['urls']['10100024']),
 ('Latest available reference year', 'APP IS STALE', 'Reference year 2024 released 27 November 2025. The app uses 2023.',
  S['urls']['daily']),
 ('Ontario spending shares', 'MULTIPLE ERRORS', '"Other" coded at 1% against an actual 15.6% — Ontario\'s second-largest '
  'sector. Debt coded at 9% against 5.5% on the province\'s own books.', V['prov_actuals']['ON']['src']),
 ('Quebec spending shares', 'PARTLY CORRECT', 'Health at 40% and debt at 7% both hold up — the only two coded provincial values '
  'in this audit that do. "Other" at 2% against an actual 11.5%.', V['prov_actuals']['QC']['src']),
 ('Alberta spending shares', 'MULTIPLE ERRORS', 'Seven of ten categories out by 2 points or more, including transport at 8% '
  'against 3.1% and environment at 4% against 0.9%.', V['prov_actuals']['AB']['src']),
 ('Nova Scotia spending shares', 'MULTIPLE ERRORS', 'Eight of ten out by 2 points or more. "Other" at 2% against 15.0%; debt at '
  '8% against 4.8%.', V['prov_actuals']['NS']['src']),
 ('CHT allocations by province', 'WRONG', 'Only BC is right. The coded national total is correct, but the territories\' $161M '
  'has been redistributed across the ten provinces.', V['cht_src']),
 ('Do territories receive CHT?', 'YES — app is wrong', 'Yukon $56M, NWT $55M, Nunavut $50M for 2023-24, alongside their TFF. '
  'Confirmed by Finance Canada\'s allocation tables, its letters to the territories, and the monthly payment tables.',
  V['cht_src']),
 ('CHT denominators', 'STALE / WRONG MEASURE', 'Alberta\'s $62.1B is FY2021-22 program expense. Nova Scotia\'s $13.2B matches '
  'no NS expense figure in five years. All denominators predate their numerators, biasing every share high.',
  'Provincial public accounts; StatCan 10-10-0017-01'),
 ('Federal spending line items', 'NOT CHECKED', 'The federal dollar figures ($54.7B CHT, $83.1B elderly benefits, $55.6B debt '
  'charges and the rest) and the $544B denominator were not traced to Public Accounts or Budget 2025 in this pass. The '
  'internal inconsistencies at F-09 to F-12 were found by arithmetic on the app\'s own stated figures, not by re-deriving them.',
  'Reviewer to verify against Public Accounts 2023-24 Vol. I and Budget 2025'),
 ('Federal category shares', 'NOT CHECKED', 'Thirteen of the twenty categories have no dollar figure to check against. A full '
  'reconciliation of federal spending to these twenty categories has not been attempted and is the largest outstanding piece of '
  'work.', 'Reviewer'),
 ('Remaining nine provincial jurisdictions', 'NOT CHECKED', 'MB, NB, NL, PE, SK, NT, NU, YT and BC were not individually traced '
  'to their public accounts. Given that all four jurisdictions that were checked failed, these should be assumed wrong until '
  'shown otherwise.', 'Reviewer'),
]
r = 4
VERD_FILL = {'CORRECT': GREENF, 'CORRECT except Yukon': AMBER, 'CORRECT — do not change': GREENF,
             'WRONG': REDF, 'CITED WRONGLY': REDF, 'MISSING FROM APP': REDF, 'MULTIPLE ERRORS': REDF,
             'YES — app is wrong': REDF, 'STALE / WRONG MEASURE': REDF, 'APP IS STALE': AMBER,
             'PARTLY CORRECT': AMBER, 'CONSTRAINED': AMBER, 'NONE EXIST': GREENF, 'NOT CHECKED': BLUEF}
for item, verdict, found, src in LOG:
    put(ws, r, 1, item, font=BOLD, align=WRAP)
    put(ws, r, 2, verdict, font=BOLD, align=WRAP, fill=VERD_FILL.get(verdict, GREY))
    put(ws, r, 3, found, font=SMALL, align=WRAP)
    put(ws, r, 4, src, font=SMALL, align=WRAP)
    put(ws, r, 5, '', fill=BLUEF); put(ws, r, 6, '', fill=BLUEF)
    ws.row_dimensions[r].height = max(30, 11 * (len(found) // 62 + 1))
    r += 1

wb.calculation.fullCalcOnLoad = True
wb.save(OUT)
print('wrote', OUT)
