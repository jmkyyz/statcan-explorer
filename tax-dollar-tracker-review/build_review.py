#!/usr/bin/env python3
"""Build the Tax Dollar Tracker review workbook.

Six tabs, aimed at about an hour of a volunteer accountant's time. Replaces the
earlier twelve-tab, forty-eight-finding version, most of whose findings have since
been fixed — handing reviewers a register of corrected problems wastes the goodwill
we are asking for.

Every computed cell is a live Excel formula built from the app's own inputs, so a
reviewer can change a bracket or a share and watch the answer move. Nothing is a
pasted constant except the source figures themselves.

    python3 build_review.py
"""

import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = json.load(open(os.path.join(HERE, 'app_current.json')))
FED = json.load(open(os.path.join(HERE, 'federal_shares_2024_25.json')))
PROV = json.load(open(os.path.join(HERE, 'provincial_shares_2024.json')))
OUT = os.path.join(os.path.dirname(HERE), 'tax-dollar-tracker-review.xlsx')

F = 'Aptos Narrow'
H1 = Font(name=F, size=15, bold=True, color='FFFFFF')
SUB = Font(name=F, size=10, color='D6E4FF')
H2 = Font(name=F, size=11, bold=True, color='FFFFFF')
BOLD = Font(name=F, size=10, bold=True)
BASE = Font(name=F, size=10)
SMALL = Font(name=F, size=9, color='595959')
ITAL = Font(name=F, size=10, italic=True, color='404040')
LEDE = Font(name=F, size=11, bold=True, color='1F3864')
LINK = Font(name=F, size=10, color='0563C1', underline='single')

NAVY = PatternFill('solid', fgColor='1F3864')
HDR = PatternFill('solid', fgColor='2563EB')
GREY = PatternFill('solid', fgColor='F2F2F2')
YOURS = PatternFill('solid', fgColor='FFF9DB')
GOOD = PatternFill('solid', fgColor='E2EFDA')
WARN = PatternFill('solid', fgColor='FFF2CC')

thin = Side(style='thin', color='BFBFBF')
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical='top')
TOP = Alignment(vertical='top')
CTR = Alignment(horizontal='center', vertical='center')

MONEY = '$#,##0'
MILL = '$#,##0,,"M"'
PCT2 = '0.00"%"'
PCT1 = '0.0"%"'

wb = Workbook()
wb.remove(wb.active)


def ontario_health_premium_formula(inc):
    """Nested IF reproducing the app's ontarioHealthPremium(), built rather than typed.

    Hand-writing a ten-deep nest is how you end up one closing bracket short.
    """
    steps = [
        (20000, '0'),
        (25000, f'MIN(300,({inc}-20000)*0.06)'),
        (36000, '300'),
        (38500, f'MIN(450,300+({inc}-36000)*0.06)'),
        (48000, '450'),
        (48600, f'MIN(600,450+({inc}-48000)*0.25)'),
        (72000, '600'),
        (72600, f'MIN(750,600+({inc}-72000)*0.25)'),
        (200000, '750'),
        (200600, f'MIN(900,750+({inc}-200000)*0.25)'),
    ]
    expr = '900'
    for limit, value in reversed(steps):
        expr = f'IF({inc}<={limit},{value},{expr})'
    assert expr.count('(') == expr.count(')'), 'unbalanced OHP formula'
    return expr


def sheet(name, widths, freeze='A3'):
    ws = wb.create_sheet(name)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.sheet_view.showGridLines = False
    if freeze:
        ws.freeze_panes = freeze
    return ws


def title(ws, text, sub, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(1, 1, text)
    c.font, c.fill, c.alignment = H1, NAVY, Alignment(vertical='center', indent=1)
    ws.row_dimensions[1].height = 30
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    c = ws.cell(2, 1, sub)
    c.font, c.fill, c.alignment = SUB, NAVY, Alignment(vertical='center', indent=1, wrap_text=True)
    ws.row_dimensions[2].height = 26


def put(ws, r, c, v, font=BASE, fmt=None, fill=None, align=TOP, border=True):
    cell = ws.cell(r, c, v)
    cell.font = font
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    if align:
        cell.alignment = align
    if border:
        cell.border = BOX
    return cell


def header(ws, r, labels):
    for i, lab in enumerate(labels, start=1):
        c = put(ws, r, i, lab, font=H2, fill=HDR, align=Alignment(wrap_text=True, vertical='center'))
    ws.row_dimensions[r].height = 28
    return r + 1


def para(ws, r, text, ncols, font=BASE, height=None, fill=None):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    c = ws.cell(r, 1, text)
    c.font, c.alignment = font, Alignment(wrap_text=True, vertical='top', indent=1)
    if fill:
        for i in range(1, ncols + 1):
            ws.cell(r, i).fill = fill
    if height:
        ws.row_dimensions[r].height = height
    return r + 1


# ══════════════════════════════════════════════════════════════════════
# 1. Start here
# ══════════════════════════════════════════════════════════════════════
ws = sheet('1. Start here', [3, 96, 30, 30], freeze=None)
title(ws, 'Tax Dollar Tracker — accuracy review',
      'A web tool that estimates a Canadian filer\'s income tax and shows where those dollars go. '
      'Please gut-check it before publication.', 4)

r = 4
r = para(ws, r, 'What the tool claims', 4, font=LEDE)
r = para(ws, r,
         'You enter an annual income and a province. It calculates your 2025 federal and provincial '
         'income tax, then divides that tax across 22 spending categories in proportion to what the two '
         'levels of government actually spent. Federal spending comes from the 2024–25 Public Accounts; '
         'provincial from Statistics Canada\'s 2024 functional (CCOFOG) estimates.', 4, height=48)
r += 1

r = para(ws, r, 'The four things worth your time', 4, font=LEDE)
for n, q in [
    ('1', 'Is the tax arithmetic right? Tab 2 lays out all 13 jurisdictions with live formulas. '
          'The brackets have been checked against CRA\'s 2025 forms once already, so the useful '
          'question is whether the structure is right — surtax, health premium, abatement, ordering.'),
    ('2', 'Do the federal shares tie to the Public Accounts? Tab 3 gives each category the line it '
          'came from. The question is whether the mapping is defensible, not whether the numbers were '
          'transcribed correctly.'),
    ('3', 'Is the provincial construction sound? Tab 4. Ten categories built from CCOFOG functions on '
          'a consolidated provincial-territorial-local basis.'),
    ('4', 'Are the judgment calls the right ones? Tab 5. These are editorial decisions, not arithmetic, '
          'and they are where an outside view is worth most.'),
]:
    put(ws, r, 1, n, font=BOLD, align=CTR)
    put(ws, r, 2, q, align=WRAP)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
    for i in (3, 4):
        ws.cell(r, i).border = BOX
    ws.row_dimensions[r].height = 42
    r += 1
r += 1

r = para(ws, r, 'How to use this workbook', 4, font=LEDE)
r = para(ws, r,
         'Every computed cell is a live formula, so you can change an input and watch the result move. '
         'Cream-shaded columns headed "Your view" are for you — write anything, they feed nothing. '
         'If a formula disagrees with what you expect, that is the finding: say so in the row.', 4, height=44)
r += 1

r = para(ws, r, 'What is deliberately NOT modelled', 4, font=LEDE)
r = para(ws, r,
         'CPP and EI are excluded from the tax total because they are contributions to benefits you get '
         'back, not taxes. The credits they generate, the Canada Employment Amount, and provincial '
         'low-income reductions are also not applied, so the tax figure runs high — by about 3% at '
         '$200,000 and over 20% at $30,000. None of that changes the spending split, which is what the '
         'tool exists to show. Tab 6 has the full list.', 4, height=58)
r += 1

r = para(ws, r, 'Key figures, so you know roughly what to expect', 4, font=LEDE)
r = header(ws, r, ['', 'Figure', 'Value', 'Source'])
for lab, val, src in [
    ('Federal total expenses 2024–25, excl. net actuarial losses', FED['_denominator'] * 1e6,
     'Public Accounts 2025, Vol I, Table 3.6'),
    ('Federal revenues 2024–25', 510951e6, 'Public Accounts 2025, Vol I, Section 2'),
    ('Federal annual deficit 2024–25', 36348e6, 'derived: 547,299 − 510,951'),
    ('Ontario provincial-territorial-local expenditure 2024',
     PROV['shares']['ON']['_totalExpenditureM'] * 1e6, 'StatCan 10-10-0005-01'),
]:
    put(ws, r, 2, lab)
    put(ws, r, 3, val, fmt=MILL, font=BOLD)
    put(ws, r, 4, src, font=SMALL, align=WRAP)
    r += 1

# ══════════════════════════════════════════════════════════════════════
# 2. Tax calculation
# ══════════════════════════════════════════════════════════════════════
NB = 8  # widest schedule is Newfoundland's eight brackets
# Incomes at which the workbook can compare its own formula against the app. app_current.json
# carries the app's output at exactly these, so anything else is exploration, not a mismatch.
ANCHORS = [40000, 75000, 130000, 250000]
REF0 = 2 + 2 * NB + 8            # first column of the app-reference block
ws = sheet('2. Tax calculation',
           [22, 11] + [10, 7] * NB + [12, 11, 12, 12, 11, 10, 26] + [11] * len(ANCHORS))
NCOL = 2 + 2 * NB + 7
title(ws, 'Tax calculation — 2025',
      'Every tax figure here is a live formula reading the bracket cells beside it. Change a threshold, '
      'a rate, the basic personal amount or the income, and the tax recalculates at whatever you enter.',
      NCOL)

r = 4
INC_ROW = r
anchors_txt = ', '.join(f'${a:,}' for a in ANCHORS)
put(ws, r, 1, 'Income to test:', font=BOLD)
inc_cell = put(ws, r, 2, 130000, fmt=MONEY,
               font=Font(name=F, size=10, bold=True, color='0000FF'), fill=YOURS)
put(ws, r, 3, f'← recalculates at any amount. To check the formula against the app itself, '
              f'use one of its four preset incomes: {anchors_txt}.', font=ITAL)
ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=NCOL)
INC = f'$B${INC_ROW}'
r += 2

r = para(ws, r,
         'Bracket tax is the sum over brackets of (income capped at this threshold, less the previous '
         'threshold, floored at zero) times the rate. The basic personal amount is then credited at the '
         'lowest rate. Ontario adds a surtax of 20% of Ontario tax over $5,710 plus a further 36% over '
         '$7,307, then the Ontario Health Premium. Quebec\'s federal tax is reduced 16.5% by the '
         'abatement. A blank threshold means the top bracket, with no upper limit.', NCOL, height=54)
r += 1

hdr = ['Jurisdiction', 'BPA']
for i in range(NB):
    hdr += [f'Threshold {i+1}', 'Rate']
hdr += ['Bracket tax', 'BPA credit', 'Surtax + OHP', 'Tax (formula)', 'App says', 'Diff', 'Your view']
hdr += [f'app @ ${a:,}' for a in ANCHORS]
r = header(ws, r, hdr)
HDR_ROW = r - 1
REF_HDR = (f'${get_column_letter(REF0)}${HDR_ROW}:'
           f'${get_column_letter(REF0 + len(ANCHORS) - 1)}${HDR_ROW}')
# The header cells double as the lookup key, so they must be the numbers themselves.
for j, a in enumerate(ANCHORS):
    put(ws, r - 1, REF0 + j, a, font=H2, fill=HDR, fmt='#,##0',
        align=Alignment(horizontal='center', vertical='center'))
top = r

for code in ['FED'] + sorted(APP['provinces']):
    if code == 'FED':
        name, bpa, brackets = 'Federal', APP['fedBpa'], APP['fedBrackets']
    else:
        p = APP['provinces'][code]
        name, bpa, brackets = f"{p['name']} ({code})", p['bpa'], p['brackets']

    put(ws, r, 1, name, font=BOLD)
    put(ws, r, 2, bpa, fmt=MONEY)
    for i in range(NB):
        tcol, rcol = 3 + 2 * i, 4 + 2 * i
        if i < len(brackets):
            lim, rate = brackets[i]
            put(ws, r, tcol, lim if lim else None, fmt='#,##0')
            put(ws, r, rcol, rate, fmt='0.0000')
        else:
            put(ws, r, tcol, None)
            put(ws, r, rcol, None)

    # Bracket tax: one MAX/MIN term per bracket, referencing the cells to the left.
    terms = []
    for i in range(len(brackets)):
        T = f'{get_column_letter(3 + 2 * i)}{r}'
        R = f'{get_column_letter(4 + 2 * i)}{r}'
        prev = '0' if i == 0 else f'{get_column_letter(3 + 2 * (i - 1))}{r}'
        terms.append(f'MAX(0,IF({T}="",{INC},MIN({INC},{T}))-{prev})*{R}')
    cBrk = get_column_letter(3 + 2 * NB)
    cCr = get_column_letter(4 + 2 * NB)
    cSur = get_column_letter(5 + 2 * NB)
    cTax = get_column_letter(6 + 2 * NB)
    cApp = get_column_letter(7 + 2 * NB)
    cDif = get_column_letter(8 + 2 * NB)

    put(ws, r, 3 + 2 * NB, '=' + '+'.join(terms), fmt=MONEY)
    put(ws, r, 4 + 2 * NB, f'=-B{r}*{get_column_letter(4)}{r}', fmt=MONEY)

    if code == 'ON':
        base = f'MAX(0,ROUND({cBrk}{r}+{cCr}{r},0))'
        surtax = f'MAX(0,{base}-5710)*0.2+MAX(0,{base}-7307)*0.36'
        ohp = ontario_health_premium_formula(INC)
        put(ws, r, 5 + 2 * NB, f'={surtax}+{ohp}', fmt=MONEY)
        put(ws, r, 6 + 2 * NB, f'=ROUND({base}+{cSur}{r},0)', fmt=MONEY, font=BOLD)
    elif code == 'FED':
        put(ws, r, 5 + 2 * NB, 0, fmt=MONEY)
        put(ws, r, 6 + 2 * NB, f'=MAX(0,ROUND({cBrk}{r}+{cCr}{r},0))', fmt=MONEY, font=BOLD)
    elif code == 'QC':
        put(ws, r, 5 + 2 * NB, 0, fmt=MONEY)
        put(ws, r, 6 + 2 * NB, f'=MAX(0,ROUND({cBrk}{r}+{cCr}{r},0))', fmt=MONEY, font=BOLD)
    else:
        put(ws, r, 5 + 2 * NB, 0, fmt=MONEY)
        put(ws, r, 6 + 2 * NB, f'=MAX(0,ROUND({cBrk}{r}+{cCr}{r},0))', fmt=MONEY, font=BOLD)

    # Reference values the app produces at each anchor income, off to the right. "App says"
    # looks up whichever anchor the income cell currently matches, so a reviewer can move the
    # income freely without the comparison turning into a false alarm.
    for j, inc in enumerate(ANCHORS):
        v = (APP['samples']['ON'][str(inc)]['fed'] if code == 'FED'
             else APP['samples'][code][str(inc)]['prov'])
        put(ws, r, REF0 + j, v, fmt=MONEY, font=SMALL, fill=GREY)
    ref = f'{get_column_letter(REF0)}{r}:{get_column_letter(REF0 + len(ANCHORS) - 1)}{r}'
    put(ws, r, 7 + 2 * NB,
        f'=IFERROR(INDEX({ref},MATCH({INC},{REF_HDR},0)),"—")', fmt=MONEY)
    put(ws, r, 8 + 2 * NB,
        f'=IF(ISNUMBER({cApp}{r}),{cTax}{r}-{cApp}{r},"")', fmt=MONEY, font=SMALL)
    put(ws, r, 9 + 2 * NB, '', fill=YOURS)
    r += 1
bot = r - 1

cDif = get_column_letter(8 + 2 * NB)
put(ws, r, 1, 'Check', font=BOLD, fill=GREY)
# Three states, not two. The old version only knew "matches" and "disagrees", so exploring at
# any income other than the single anchor raised a false alarm — which teaches a reviewer to
# ignore the check exactly when it might matter. anchors_txt was set above, by the income cell.
# MAX(MAX(range),-MIN(range)) is the largest absolute value without needing array entry.
put(ws, r, 2,
    f'=IF(COUNT({cDif}{top}:{cDif}{bot})=0,'
    f'"Exploring at an income the app was not sampled at — set the income cell to '
    f'{anchors_txt} to compare against the app.",'
    f'IF(MAX(MAX({cDif}{top}:{cDif}{bot}),-MIN({cDif}{top}:{cDif}{bot}))<=1,'
    f'"Every formula matches the app at this income (within $1 of rounding) — OK",'
    f'"A FORMULA DISAGREES WITH THE APP — see the Diff column"))', font=BOLD, fill=GOOD)
ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=NCOL)
r += 2

r = para(ws, r,
         '"App says" is what the tool itself reports — provincial tax, or federal tax on the first row. '
         'It shows "—" at any income outside the four presets, because there is nothing to compare it '
         'against there, not because the formula is wrong.', NCOL, height=30)
r += 1

# The abatement is the one piece of the tax structure not visible in the grid above, because it
# reduces federal rather than provincial tax. Shown separately so a reviewer can check it.
r = para(ws, r, 'Quebec federal abatement', NCOL, font=LEDE)
put(ws, r, 1, 'Federal tax before abatement', font=BOLD)
put(ws, r, 2, f'={cTax}{top}', fmt=MONEY)
put(ws, r, 3, 'less 16.5%, Quebec only', font=ITAL)
ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)
r += 1
put(ws, r, 1, 'Federal tax after abatement', font=BOLD)
put(ws, r, 2, f'=ROUND(B{r-1}*(1-0.165),0)', fmt=MONEY, font=BOLD)
# Same anchor lookup as the grid above — this check had the identical fixed-income flaw.
for j, inc in enumerate(ANCHORS):
    put(ws, r, REF0 + j, APP['samples']['QC'][str(inc)]['fed'],
        fmt=MONEY, font=SMALL, fill=GREY)
qref = f'{get_column_letter(REF0)}{r}:{get_column_letter(REF0 + len(ANCHORS) - 1)}{r}'
put(ws, r, 3, f'=IFERROR(INDEX({qref},MATCH({INC},{REF_HDR},0)),"—")', fmt=MONEY)
put(ws, r, 4,
    f'=IF(NOT(ISNUMBER(C{r})),"Set the income to an anchor value to compare.",'
    f'IF(B{r}=C{r},"matches the app — OK","DISAGREES WITH THE APP"))',
    font=BOLD, fill=GOOD)
ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=8)
r += 1
r = para(ws, r,
         'Quebec operates its own tax system, and Ottawa returns 16.5% of net federal tax to compensate '
         'for the tax room Quebec occupies. It reduces federal tax, not provincial, which is why it does '
         'not appear in the grid above. Like the grid, the comparison here only resolves at the four '
         'preset incomes.', NCOL, height=40)
r += 1

r = para(ws, r,
         'A fixed reference table, independent of the income cell above — always at $130,000, for all 13 '
         'jurisdictions side by side.', NCOL, font=LEDE)
r = header(ws, r, ['Jurisdiction', 'Total tax @ $130,000', 'Effective rate', 'Marginal rate',
                   'Published marginal', 'Match?'] + [''] * (NCOL - 6))
PUBLISHED = {'ON': 43.41, 'BC': 40.70, 'QC': 45.71, 'AB': 36.00, 'NS': 43.50, 'NL': 42.30,
             'MB': 43.40, 'SK': 38.50, 'NB': 42.00, 'PE': 43.62, 'YT': 36.90, 'NT': 38.20,
             'NU': 35.00}
for code in sorted(APP['provinces']):
    s = APP['samples'][code]['130000']
    put(ws, r, 1, f"{APP['provinces'][code]['name']} ({code})")
    put(ws, r, 2, s['total'], fmt=MONEY)
    # Divide by the literal $130,000 this row is anchored to — NOT by the income cell above,
    # which the reviewer is explicitly invited to change. An earlier version divided by that
    # cell, so it read correctly only by coincidence, while the income cell held $130,000.
    put(ws, r, 3, f'=B{r}/130000', fmt='0.0%')
    put(ws, r, 4, s['marginal'], fmt=PCT2)
    put(ws, r, 5, '', fill=YOURS)
    put(ws, r, 6, '', fill=YOURS)
    for i in range(7, NCOL + 1):
        ws.cell(r, i).border = BOX
    r += 1
r += 1
r = para(ws, r,
         'Columns E and F are left blank on purpose — if you have a marginal rate table to hand, that is '
         'the fastest independent check in this workbook. For reference, all 13 top combined rates were '
         'checked against published 2025 figures and matched, including Newfoundland at 54.80% (which '
         'applies only above $1,128,858) and PEI at 52.00% for 2025.', NCOL, height=46, fill=GOOD)

# ══════════════════════════════════════════════════════════════════════
# 3. Federal allocation
# ══════════════════════════════════════════════════════════════════════
ws = sheet('3. Federal allocation', [30, 15, 11, 11, 62, 30])
title(ws, 'Federal allocation — 2024–25 Public Accounts actuals',
      'Each category traced to a printed line. T3.6 = external expenses by ministry segment, '
      'T3.7 = major transfer payments, T3.10 = expenditures under statutory authorities.', 6)

r = 4
r = para(ws, r,
         'Denominator is total expenses excluding net actuarial losses, $543,279M. Transfers and debt are '
         'taken as program lines; the functional categories are ministry totals net of each ministry\'s own '
         'public debt charges. No ministry appears on both sides, so the two cuts cannot double-count. '
         '"Other" is the denominator less every named category — a residual, not a plug.', 6, height=52)
r += 1

r = header(ws, r, ['Category', 'Amount ($M)', 'Share', 'Check', 'Source line', 'Your view'])
top = r
order = [c['key'] for c in APP['cats']]
for key in order:
    amt, pct, note = FED[key]
    label = next(c['label'] for c in APP['cats'] if c['key'] == key)
    put(ws, r, 1, label, font=BOLD if key == 'other' else BASE)
    put(ws, r, 2, amt, fmt='#,##0')
    put(ws, r, 3, pct, fmt=PCT2)
    put(ws, r, 4, f'=B{r}/{FED["_denominator"]}*100', fmt=PCT2, font=SMALL)
    put(ws, r, 5, note, font=SMALL, align=WRAP)
    put(ws, r, 6, '', fill=YOURS)
    ws.row_dimensions[r].height = 26
    r += 1
bot = r - 1

put(ws, r, 1, 'TOTAL', font=BOLD, fill=GREY)
put(ws, r, 2, f'=SUM(B{top}:B{bot})', fmt='#,##0', font=BOLD, fill=GREY)
put(ws, r, 3, f'=SUM(C{top}:C{bot})', fmt=PCT2, font=BOLD, fill=GREY)
put(ws, r, 4, f'=SUM(D{top}:D{bot})', fmt=PCT2, font=BOLD, fill=GREY)
put(ws, r, 5, f'=IF(ABS(SUM(C{top}:C{bot})-100)<0.005,"Shares sum to 100.00 — OK",'
              f'"SHARES DO NOT SUM TO 100")', font=BOLD, fill=GOOD)
put(ws, r, 6, '', fill=YOURS)
r += 2

r = para(ws, r,
         'Veterans Affairs is the one category not on the ministry basis. The Public Accounts show that '
         'segment at $546M because veterans\' disability and future benefits are recognised as personnel '
         'expenses government-wide — publishing it would say Canada spends 0.1% of federal expenses on '
         'veterans. The figure used is total expenses from Veterans Affairs\' own audited departmental '
         'financial statements, $7,209M, with the difference taken out of Other. Please sanity-check that '
         'this is the right call.', 6, height=62, fill=WARN)

# ══════════════════════════════════════════════════════════════════════
# 4. Provincial allocation
# ══════════════════════════════════════════════════════════════════════
CATS10 = ['health', 'education', 'socialEI', 'debt', 'transport',
          'justice', 'housing', 'environment', 'admin', 'other']
LABEL10 = {'health': 'Health', 'education': 'Education', 'socialEI': 'Social assistance',
           'debt': 'Debt servicing', 'transport': 'Transport', 'justice': 'Justice & safety',
           'housing': 'Housing', 'environment': 'Environment', 'admin': 'Administration',
           'other': 'Other'}
MAP10 = {
    'health': 'CCOFOG 707 Health',
    'education': 'CCOFOG 709 Education (includes college and university)',
    'socialEI': 'CCOFOG 710 Social protection',
    'debt': 'CCOFOG 7017 Public debt transactions',
    'transport': 'CCOFOG 7045 Transport',
    'justice': 'CCOFOG 703 Public order and safety',
    'housing': 'CCOFOG 706 Housing and community amenities',
    'environment': 'CCOFOG 705 Environmental protection',
    'admin': 'CCOFOG 701 General public services LESS 7017',
    'other': 'CCOFOG 702 Defence + 708 Recreation/culture + (704 Economic affairs LESS 7045)',
}

ws = sheet('4. Provincial allocation', [26] + [11] * 10 + [11, 28])
title(ws, 'Provincial allocation — StatCan 10-10-0005-01, reference year 2024',
      'Component: consolidated provincial-territorial and local governments. The ten categories are a '
      'partition of the ten CCOFOG divisions, so each jurisdiction sums to exactly 100 by construction.', 13)

r = 4
r = para(ws, r,
         'The universe includes municipalities, school boards, hospitals and universities alongside the '
         'province. That is wider than "the provincial government", and it is the basis Statistics Canada '
         'publishes for comparing jurisdictions, because provinces delegate different functions to '
         'municipalities. CCOFOG excludes capital acquisition and consumption of fixed capital, so these '
         'are operating expenses — which understates transport most.', 13, height=52)
r += 1

r = header(ws, r, ['Jurisdiction'] + [LABEL10[c] for c in CATS10] + ['Sum', 'Total exp. ($M)'])
top = r
for code in sorted(PROV['shares']):
    row = PROV['shares'][code]
    put(ws, r, 1, f"{APP['provinces'][code]['name']} ({code})", font=BOLD)
    for i, c in enumerate(CATS10):
        put(ws, r, 2 + i, row[c], fmt=PCT1)
    put(ws, r, 12, f'=SUM(B{r}:K{r})', fmt=PCT1, font=BOLD,
        fill=GOOD)
    put(ws, r, 13, row['_totalExpenditureM'], fmt='#,##0')
    r += 1
bot = r - 1
put(ws, r, 1, 'Check', font=BOLD, fill=GREY)
put(ws, r, 2, f'=IF(AND(MIN(L{top}:L{bot})>99.99,MAX(L{top}:L{bot})<100.01),'
              f'"All 13 jurisdictions sum to exactly 100.0 — OK","A JURISDICTION DOES NOT SUM TO 100")',
    font=BOLD, fill=GOOD)
ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=13)
r += 2

r = para(ws, r, 'How each category is built', 13, font=LEDE)
r = header(ws, r, ['Category', 'CCOFOG mapping'] + [''] * 11)
for c in CATS10:
    put(ws, r, 1, LABEL10[c], font=BOLD)
    put(ws, r, 2, MAP10[c], font=SMALL, align=WRAP)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=13)
    for i in range(3, 14):
        ws.cell(r, i).border = BOX
    r += 1
r += 1
r = para(ws, r,
         'Why this table rather than the provincial-government-only series: the provincial-and-territorial '
         'component of table 10-10-0024-01 publishes only the 10 top-level divisions, so Transport [7045] '
         'and Public debt transactions [7017] do not exist there. The consolidated component of 10-10-0005-01 '
         'carries all 60 CCOFOG members, so every category comes from one table at one vintage on one '
         'universe. Its footnote 5 also states this series can be compared across jurisdictions.',
         13, height=60, fill=GOOD)

# ══════════════════════════════════════════════════════════════════════
# 5. Judgment calls
# ══════════════════════════════════════════════════════════════════════
ws = sheet('5. Judgment calls', [4, 30, 52, 52, 32])
title(ws, 'Judgment calls',
      'Editorial decisions rather than arithmetic. These are where an outside view is worth most — '
      'please disagree freely.', 5)

CALLS = [
    ('The provincial universe',
     'The provincial column consolidates municipalities, school boards, hospitals and universities with '
     'the province. Chosen because it reproduces all ten categories from one table and because StatCan '
     'says this basis can be compared across jurisdictions.',
     'The alternative — provincial government only — answers the literal question "where does my '
     'provincial tax go" more exactly, but has no transport line at all, starts only at 2015, and carries '
     'a footnote advising against comparing provinces. Municipal spending is also partly funded by '
     'property tax, which this tool does not model.'),
    ('Mixing program and ministry lines federally',
     'Transfers and debt are program lines; functional categories are ministry totals. Kept because '
     'readers want to see the Canada Health Transfer and Canada Social Transfer as their own rows.',
     'It is not one clean cut of the accounts. Going all-ministry or all-functional would be more '
     'coherent but would bury the transfers inside Finance and Health.'),
    ('Federal transfers appear on both sides',
     'The CHT, CST, Equalization and TFF are shown as federal rows AND are inside the provincial column, '
     'because your province spends those same dollars. The overlap is disclosed, not netted out.',
     'An earlier version subtracted each province\'s CHT share from health and renormalised, which moved '
     'the money onto the other nine categories rather than removing it. That was removed. Netting it out '
     'properly would need per-province CST, Equalization and TFF allocations.'),
    ('Income tax is assumed to fund everything proportionally',
     'Your income tax is spread across all spending in proportion to what was spent. This is the method '
     'the UK uses for its Annual Tax Summary.',
     'No revenue source is earmarked. Income tax is roughly half of federal revenue and about a quarter '
     'of provincial revenue, so it funds no such uniform slice. This is the tool\'s central assumption '
     'and is stated on the page.'),
    ('Deficits are not shown',
     'The tool allocates tax across total spending, without adjusting for the portion funded by borrowing.',
     'In 2024–25 Ottawa spent $547.3B against revenues of $511.0B, so about 6.6 cents of every dollar '
     'spent was borrowed rather than taxed. A slice of every category is therefore on credit. Should the '
     'tool say so, model it, or leave it to the accompanying article?'),
    ('Employment credits and low-income reductions are not applied',
     'Only the basic personal amount is applied, so the tax figure runs high — about 3% at $200,000 and '
     'over 20% at $30,000.',
     'Applying them properly means CPP and EI credits, the Canada Employment Amount, and low-income '
     'reductions in at least six provinces, re-verified annually. None of it changes the spending split. '
     'Is disclosure enough?'),
]

r = 4
r = header(ws, r, ['', 'Decision', 'What we did, and why', 'The case against / what it costs', 'Your view'])
for i, (name, did, against) in enumerate(CALLS, start=1):
    put(ws, r, 1, i, font=BOLD, align=CTR)
    put(ws, r, 2, name, font=BOLD, align=WRAP)
    put(ws, r, 3, did, align=WRAP)
    put(ws, r, 4, against, align=WRAP)
    put(ws, r, 5, '', fill=YOURS)
    ws.row_dimensions[r].height = 74
    r += 1

# ══════════════════════════════════════════════════════════════════════
# 6. Known gaps
# ══════════════════════════════════════════════════════════════════════
ws = sheet('6. Known gaps', [34, 74, 20, 30])
title(ws, 'Known gaps',
      'Things we know are missing or simplified. Listed so you do not spend time rediscovering them — '
      'but do say if you think any are more serious than we have assumed.', 4)

GAPS = [
    ('CPP and EI credits', 'Premiums paid generate non-refundable credits; the enhanced portion of CPP is '
     'a deduction. Not applied, so tax runs high at every income.', 'Deliberate'),
    ('Canada Employment Amount', '$1,471 federal credit claimable by most employees. Not applied.',
     'Deliberate'),
    ('Provincial low-income reductions', 'Ontario\'s eliminates provincial tax below $18,569 and phases '
     'out by $24,391; Ontario also has the separate LIFT credit. BC applies one at source. Newfoundland, '
     'Nova Scotia, New Brunswick and PEI have their own. None modelled.', 'Deliberate'),
    ('Marital status, dependants, RRSP', 'Not collected, so no credit that depends on them is applied.',
     'Deliberate'),
    ('Taxable vs gross income', 'The figure entered is treated as taxable income. Someone entering a '
     'salary is entering gross employment income, so their real taxable income is lower.', 'Disclosed'),
    ('Basic personal amount phase-out', 'The federal BPA phases down above $177,882. Not modelled.',
     'Minor, high incomes'),
    ('Top-up Tax Credit (line 34990)', 'Applies only to credits claimed on amounts over $57,375. The tool '
     'models one credit, the $16,129 BPA, so it can never engage.', 'Not applicable'),
    ('Capital spending, provincial side', 'CCOFOG excludes acquisition of non-financial assets and '
     'consumption of fixed capital. Understates transport most.', 'Source limitation'),
    ('Government business enterprises', 'Excluded from CCOFOG by definition.', 'Source limitation'),
    ('Provincial vintage', 'Provincial data is reference year 2024; federal is fiscal 2024–25. Close but '
     'not identical periods.', 'Disclosed'),
]

r = 4
r = header(ws, r, ['Gap', 'What it means', 'Status', 'Your view'])
for name, what, status in GAPS:
    put(ws, r, 1, name, font=BOLD, align=WRAP)
    put(ws, r, 2, what, align=WRAP)
    put(ws, r, 3, status, font=ITAL, align=WRAP)
    put(ws, r, 4, '', fill=YOURS)
    ws.row_dimensions[r].height = 34
    r += 1

wb.save(OUT)
print(f'wrote {OUT}')
print(f'  {len(wb.sheetnames)} tabs: ' + ', '.join(wb.sheetnames))
