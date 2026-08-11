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
# Every size below is +2pt over the original draft, which read too small at 10pt body text.
# Sizes move together rather than just the 10s, so headers stay larger than body and footnotes
# stay smaller than body instead of the hierarchy inverting.
H1 = Font(name=F, size=17, bold=True, color='FFFFFF')
SUB = Font(name=F, size=12, color='D6E4FF')
H2 = Font(name=F, size=13, bold=True, color='FFFFFF')
BOLD = Font(name=F, size=12, bold=True)
BASE = Font(name=F, size=12)
SMALL = Font(name=F, size=11, color='595959')
ITAL = Font(name=F, size=12, italic=True, color='404040')
LEDE = Font(name=F, size=13, bold=True, color='1F3864')
LINK = Font(name=F, size=12, color='0563C1', underline='single')

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
    ws.row_dimensions[1].height = 36
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    c = ws.cell(2, 1, sub)
    c.font, c.fill, c.alignment = SUB, NAVY, Alignment(vertical='center', indent=1, wrap_text=True)
    ws.row_dimensions[2].height = 31


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
    ws.row_dimensions[r].height = 34
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
         'provincial from Statistics Canada\'s 2024 functional (CCOFOG) estimates.', 4, height=58)
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
    ws.row_dimensions[r].height = 50
    r += 1
r += 1

r = para(ws, r, 'How to use this workbook', 4, font=LEDE)
r = para(ws, r,
         'Every computed cell is a live formula, so you can change an input and watch the result move. '
         'Cream-shaded columns headed "Your view" are for you — write anything, they feed nothing. '
         'If a formula disagrees with what you expect, that is the finding: say so in the row.', 4, height=53)
r += 1

r = para(ws, r, 'What is deliberately NOT modelled', 4, font=LEDE)
r = para(ws, r,
         'CPP and EI are excluded from the tax total because they are contributions to benefits you get '
         'back, not taxes. The credits they generate, the Canada Employment Amount, and provincial '
         'low-income reductions are also not applied, so the tax figure runs high — by about 3% at '
         '$200,000 and over 20% at $30,000. None of that changes the spending split, which is what the '
         'tool exists to show. Tab 6 has the full list.', 4, height=70)
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
NFED = len(APP['fedBrackets'])     # federal has 5 brackets — fewer than the widest province
# Incomes at which the workbook can compare its own formula against the app. app_current.json
# carries the app's output at exactly these, so anything else is exploration, not a mismatch.
ANCHORS = [40000, 75000, 130000, 250000]
# Column layout for the single unified table — one row per province, both tax figures on it.
PROV_END = 2 + 2 * NB              # last column of the provincial threshold/rate pairs
C_PBRK, C_PCR, C_SUR = PROV_END + 1, PROV_END + 2, PROV_END + 3
C_PROV, C_FED, C_COMB = PROV_END + 4, PROV_END + 5, PROV_END + 6
C_EFF, C_MARG = PROV_END + 7, PROV_END + 8
C_APP, C_DIFF, C_YOURS = PROV_END + 9, PROV_END + 10, PROV_END + 11
REF0 = C_YOURS + 1                 # first column of the app-reference block (off to the right)
NCOL = C_YOURS

ws = sheet('2. Tax calculation',
           [22, 11] + [10, 7] * NB + [11, 11, 10, 11, 11, 12, 10, 10, 11, 9, 26]
           + [11] * (2 * len(ANCHORS)))
title(ws, 'Tax calculation — 2025',
      'One row per jurisdiction: federal tax, provincial tax and the combined total, each a live '
      'formula reading the bracket cells beside it. Change a threshold, a rate, the basic personal '
      'amount or the income below, and every row recalculates at whatever you enter.', NCOL)

r = 4
INC_ROW = r
anchors_txt = ', '.join(f'${a:,}' for a in ANCHORS)
put(ws, r, 1, 'Income to test:', font=BOLD)
inc_cell = put(ws, r, 2, 130000, fmt=MONEY,
               font=Font(name=F, size=12, bold=True, color='0000FF'), fill=YOURS)
put(ws, r, 3, f'← recalculates every row at any amount you enter. Only four incomes can be checked '
              f'against the app itself, because that is all it was sampled at: {anchors_txt}. At any '
              f'other income the "App says" and "Marginal rate" columns show an em dash, not an error.',
    font=ITAL)
ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=NCOL)
INC = f'$B${INC_ROW}'
r += 2

# Federal brackets do not vary by province, so they live in one small block that every row
# below references by absolute cell address — change a federal rate once, all 13 rows move.
# This is a genuinely separate schedule from any one province's own bracket columns; it cannot
# share cells with a province's row, which is what an earlier draft of this tab tried to do.
FED_ROW = r
put(ws, r, 1, 'Federal (shared by every row below):', font=BOLD, fill=GREY)
put(ws, r, 2, APP['fedBpa'], fmt=MONEY, fill=GREY)
for i, (lim, rate) in enumerate(APP['fedBrackets']):
    put(ws, r, 3 + 2 * i, lim if lim else None, fmt='#,##0', fill=GREY)
    put(ws, r, 4 + 2 * i, rate, fmt='0.0000', fill=GREY)
for i in range(NFED, NB):
    put(ws, r, 3 + 2 * i, None, fill=GREY)
    put(ws, r, 4 + 2 * i, None, fill=GREY)
ws.row_dimensions[r].height = 24
r += 2

r = para(ws, r,
         'Bracket tax is the sum over brackets of (income capped at this threshold, less the previous '
         'threshold, floored at zero) times the rate. The basic personal amount is then credited at '
         'the lowest rate. Provincial tax is computed from each row\'s own threshold columns; federal '
         'tax the same way, from the shared federal row above. Ontario\'s provincial tax also carries a '
         'surtax of 20% over $5,710 and a further 36% over $7,307, plus the Ontario Health Premium; '
         'Quebec\'s federal tax is cut 16.5% by the abatement. A blank threshold means the top bracket, '
         'with no upper limit.', NCOL, height=70)
r += 1

hdr = ['Jurisdiction', 'BPA']
for i in range(NB):
    hdr += [f'Threshold {i+1}', 'Rate']
hdr += ['Prov. bracket tax', 'Prov. BPA credit', 'Surtax + OHP', 'Provincial tax', 'Federal tax',
        'Combined tax', 'Effective rate', 'Marginal rate', 'App says (combined)', 'Diff', 'Your view']
hdr += [f'marg @ ${a:,}' for a in ANCHORS] + [f'total @ ${a:,}' for a in ANCHORS]
r = header(ws, r, hdr)
HDR_ROW = r - 1
MARG_REF0, APP_REF0 = REF0, REF0 + len(ANCHORS)
MARG_HDR = f'${get_column_letter(MARG_REF0)}${HDR_ROW}:${get_column_letter(MARG_REF0 + len(ANCHORS) - 1)}${HDR_ROW}'
APP_HDR = f'${get_column_letter(APP_REF0)}${HDR_ROW}:${get_column_letter(APP_REF0 + len(ANCHORS) - 1)}${HDR_ROW}'
for j, a in enumerate(ANCHORS):
    put(ws, r - 1, MARG_REF0 + j, a, font=H2, fill=HDR, fmt='#,##0',
        align=Alignment(horizontal='center', vertical='center'))
    put(ws, r - 1, APP_REF0 + j, a, font=H2, fill=HDR, fmt='#,##0',
        align=Alignment(horizontal='center', vertical='center'))
top = r

# Federal-tax formula, shared by every row: reads the FED_ROW block above via absolute
# references, so it is identical arithmetic to the provincial calculation just applied to a
# different schedule, not a special case.
fterms = []
for i, (lim, rate) in enumerate(APP['fedBrackets']):
    T = f'${get_column_letter(3 + 2 * i)}${FED_ROW}'
    prev = '0' if i == 0 else f'${get_column_letter(3 + 2 * (i - 1))}${FED_ROW}'
    fterms.append(f'MAX(0,IF({T}="",{INC},MIN({INC},{T}))-{prev})*{rate}')
fed_bracket_tax = '+'.join(fterms)
fed_bpa_credit = f'-${get_column_letter(2)}${FED_ROW}*{APP["fedBrackets"][0][1]}'

for code in sorted(APP['provinces']):
    p = APP['provinces'][code]
    brackets = p['brackets']
    put(ws, r, 1, f"{p['name']} ({code})", font=BOLD)
    put(ws, r, 2, p['bpa'], fmt=MONEY)
    for i in range(NB):
        tcol, rcol = 3 + 2 * i, 4 + 2 * i
        if i < len(brackets):
            lim, rate = brackets[i]
            put(ws, r, tcol, lim if lim else None, fmt='#,##0')
            put(ws, r, rcol, rate, fmt='0.0000')
        else:
            put(ws, r, tcol, None)
            put(ws, r, rcol, None)

    # Provincial bracket tax: one MAX/MIN term per bracket, this row's own threshold cells.
    terms = []
    for i in range(len(brackets)):
        T = f'{get_column_letter(3 + 2 * i)}{r}'
        R = f'{get_column_letter(4 + 2 * i)}{r}'
        prev = '0' if i == 0 else f'{get_column_letter(3 + 2 * (i - 1))}{r}'
        terms.append(f'MAX(0,IF({T}="",{INC},MIN({INC},{T}))-{prev})*{R}')
    put(ws, r, C_PBRK, '=' + '+'.join(terms), fmt=MONEY)
    put(ws, r, C_PCR, f'=-B{r}*D{r}', fmt=MONEY)

    if code == 'ON':
        base = f'MAX(0,ROUND({get_column_letter(C_PBRK)}{r}+{get_column_letter(C_PCR)}{r},0))'
        surtax = f'MAX(0,{base}-5710)*0.2+MAX(0,{base}-7307)*0.36'
        ohp = ontario_health_premium_formula(INC)
        put(ws, r, C_SUR, f'={surtax}+{ohp}', fmt=MONEY)
    else:
        put(ws, r, C_SUR, 0, fmt=MONEY)
    # The app rounds base+surtax to a whole dollar BEFORE adding the (already-integer, outside
    # its narrow ramp bands) Health Premium — an outer ROUND around the full sum matches that
    # for every income this tab is used at. Dropping it, as an earlier draft of this rewrite
    # did, understated Ontario by a fraction of a dollar at every income with a live surtax.
    put(ws, r, C_PROV,
        f'=ROUND(MAX(0,ROUND({get_column_letter(C_PBRK)}{r}+{get_column_letter(C_PCR)}{r},0))'
        f'+{get_column_letter(C_SUR)}{r},0)', fmt=MONEY, font=BOLD)

    fed_expr = f'MAX(0,ROUND({fed_bracket_tax}{fed_bpa_credit},0))'
    if code == 'QC':
        fed_expr = f'ROUND({fed_expr}*(1-0.165),0)'
    put(ws, r, C_FED, f'={fed_expr}', fmt=MONEY)
    put(ws, r, C_COMB,
        f'={get_column_letter(C_PROV)}{r}+{get_column_letter(C_FED)}{r}', fmt=MONEY, font=BOLD)
    put(ws, r, C_EFF, f'={get_column_letter(C_COMB)}{r}/{INC}', fmt='0.0%')

    for j, inc in enumerate(ANCHORS):
        put(ws, r, MARG_REF0 + j, APP['samples'][code][str(inc)]['marginal'], fmt=PCT2,
            font=SMALL, fill=GREY)
    mref = f'{get_column_letter(MARG_REF0)}{r}:{get_column_letter(MARG_REF0 + len(ANCHORS) - 1)}{r}'
    put(ws, r, C_MARG, f'=IFERROR(INDEX({mref},MATCH({INC},{MARG_HDR},0)),"—")', fmt=PCT2)

    for j, inc in enumerate(ANCHORS):
        put(ws, r, APP_REF0 + j, APP['samples'][code][str(inc)]['total'], fmt=MONEY,
            font=SMALL, fill=GREY)
    aref = f'{get_column_letter(APP_REF0)}{r}:{get_column_letter(APP_REF0 + len(ANCHORS) - 1)}{r}'
    put(ws, r, C_APP, f'=IFERROR(INDEX({aref},MATCH({INC},{APP_HDR},0)),"—")', fmt=MONEY)
    put(ws, r, C_DIFF,
        f'=IF(ISNUMBER({get_column_letter(C_APP)}{r}),'
        f'{get_column_letter(C_COMB)}{r}-{get_column_letter(C_APP)}{r},"")', fmt=MONEY, font=SMALL)
    put(ws, r, C_YOURS, '', fill=YOURS)
    r += 1
bot = r - 1

put(ws, r, 1, 'Check', font=BOLD, fill=GREY)
cDiff = get_column_letter(C_DIFF)
# Three states, not two: exploring at an income the app was not sampled at is not the same as
# a genuine disagreement, and the wording says so instead of raising a false alarm either way.
put(ws, r, 2,
    f'=IF(COUNT({cDiff}{top}:{cDiff}{bot})=0,'
    f'"Exploring at an income the app was not sampled at — set the income cell to '
    f'{anchors_txt} to compare against the app.",'
    f'IF(MAX(MAX({cDiff}{top}:{cDiff}{bot}),-MIN({cDiff}{top}:{cDiff}{bot}))<=1,'
    f"\"Every jurisdiction's combined tax matches the app at this income (within $1 of rounding) — OK\","
    f'"A JURISDICTION DISAGREES WITH THE APP — see the Diff column"))', font=BOLD, fill=GOOD)
ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=NCOL)
r += 2

r = para(ws, r,
         '"App says" and the check above compare COMBINED tax — federal plus provincial together — '
         'against the total the app itself reports, matching the number on its own results page. '
         'Marginal rate and the app comparison are both reference lookups from the app\'s own output '
         'at the four incomes it was sampled at, and both show an em dash outside those four. All 13 '
         "combined marginal rates were checked separately, during development, against TaxTips.ca's "
         "published 2025 rates at each jurisdiction's own top bracket and matched exactly — including "
         'Newfoundland at 54.80%, which only applies above $1,128,858, and PEI at 52.00% for 2025 '
         "(53.00% is next year's rate, not this one's).", NCOL, height=74, fill=GOOD)

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
         '"Other" is the denominator less every named category — a residual, not a plug.', 6, height=62)
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
    ws.row_dimensions[r].height = 31
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
         'this is the right call.', 6, height=74, fill=WARN)

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
         'are operating expenses — which understates transport most.', 13, height=62)
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
         13, height=72, fill=GOOD)

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
    ws.row_dimensions[r].height = 89
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
    ws.row_dimensions[r].height = 41
    r += 1

wb.save(OUT)
print(f'wrote {OUT}')
print(f'  {len(wb.sheetnames)} tabs: ' + ', '.join(wb.sheetnames))
