"""Step 3: monthly Excel report. Every number is a live Excel formula over the Data sheet.

Labels (months, priorities, categories, dates) are written as values; all counts, rates,
medians and averages are formulas. A Checks sheet compares key formulas to the pandas
results in metrics.json. recalc_excel() opens the file in Excel (if installed) so the
saved workbook carries calculated values.
"""
import json
import subprocess
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import Table, TableStyleInfo

from config import CLEAN_DIR, METRICS_JSON, REPORTS_DIR

OUT = REPORTS_DIR / "service_desk_monthly_report.xlsx"
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE = Font(bold=True, size=14, color="1F3A5F")
SUB = Font(italic=True, size=9, color="52514E")
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))
PCT, HRS, INT = "0.0%", "#,##0.0", "#,##0"

DATA_COLS = [  # (name in sheet, source column, defined-name)
    ("Incident", "incident_id", None),
    ("Opened", "opened_at", "d_opened"),
    ("Resolved", "resolved_at", "d_resolved"),
    ("Month", "month", "d_month"),
    ("Priority", "priority", "d_priority"),
    ("Category", "category", "d_category"),
    ("Assignment group", "assignment_group", "d_group"),
    ("Resolution hours", "resolution_hours", "d_hours"),
    ("Met SLA", "met_sla", "d_sla"),
    ("Reassignments", "reassignment_count", "d_reassign"),
    ("Reassigned", "reassigned", "d_reassigned"),
    ("Reopens", "reopen_count", "d_reopens"),
    ("Reopened", "reopened", "d_reopened"),
]


def header(ws, row, labels, col=1):
    for i, h in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=h)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def title(ws, text, note=None):
    ws["A1"] = text
    ws["A1"].font = TITLE
    if note:
        ws["A2"] = note
        ws["A2"].font = SUB
    ws.sheet_view.showGridLines = False


def widths(ws, w):
    for i, x in enumerate(w, start=1):
        ws.column_dimensions[get_column_letter(i)].width = x


def fmt(cell, f):
    cell.number_format = f
    cell.border = THIN


def build():
    f = pd.read_csv(CLEAN_DIR / "fact_incident.csv", parse_dates=["opened_at", "resolved_at"])
    m = json.loads(METRICS_JSON.read_text())
    months = sorted(f.month.unique())
    priorities = ["1 - Critical", "2 - High", "3 - Moderate", "4 - Low"]
    categories = f.category.value_counts().index.tolist()
    n = len(f)
    last = n + 1

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"

    # ---------------- Data ----------------
    ds = wb.create_sheet("Data")
    header(ds, 1, [c[0] for c in DATA_COLS])
    for r_i, row in enumerate(f[[c[1] for c in DATA_COLS]].itertuples(index=False), start=2):
        for c_i, v in enumerate(row, start=1):
            if isinstance(v, float) and pd.isna(v):
                v = None
            elif isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            ds.cell(row=r_i, column=c_i, value=v)
    for r_i in range(2, last + 1):
        ds.cell(row=r_i, column=2).number_format = "yyyy-mm-dd hh:mm"
        ds.cell(row=r_i, column=3).number_format = "yyyy-mm-dd hh:mm"
    tab = Table(displayName="Incidents", ref=f"A1:{get_column_letter(len(DATA_COLS))}{last}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ds.add_table(tab)
    ds.freeze_panes = "A2"
    widths(ds, [12, 17, 17, 9, 13, 13, 16, 10, 9, 9, 10, 8, 9])
    for i, (_, _, name) in enumerate(DATA_COLS, start=1):
        if name:
            col = get_column_letter(i)
            wb.defined_names[name] = DefinedName(name, attr_text=f"Data!${col}$2:${col}${last}")

    def median_if(cell, cond):
        return ArrayFormula(cell, f'=MEDIAN(IF(({cond})*(d_hours<>""),d_hours))')

    # ---------------- Volume ----------------
    vs = wb.create_sheet("Volume")
    title(vs, "Ticket volume", "Tickets opened per month, by priority and by category (counts are COUNTIFS on the Data sheet).")
    header(vs, 4, ["Month", "Tickets", "MoM change"] + [p[4:] for p in priorities])
    for i, mo in enumerate(months):
        r = 5 + i
        vs.cell(r, 1, mo)
        vs.cell(r, 2, f"=COUNTIFS(d_month,$A{r})").number_format = INT
        vs.cell(r, 3, None if i == 0 else f"=B{r}/B{r-1}-1").number_format = '+0.0%;-0.0%'
        for j, p in enumerate(priorities):
            vs.cell(r, 4 + j, f'=COUNTIFS(d_month,$A{r},d_priority,"{p}")').number_format = INT
    tr = 5 + len(months)
    vs.cell(tr, 1, "Total").font = Font(bold=True)
    for col in [2, 4, 5, 6, 7]:
        L = get_column_letter(col)
        vs.cell(tr, col, f"=SUM({L}5:{L}{tr-1})").number_format = INT
    ch = BarChart(); ch.title = "Tickets per month"; ch.style = 10; ch.legend = None
    ch.add_data(Reference(vs, min_col=2, min_row=4, max_row=tr - 1), titles_from_data=True)
    ch.set_categories(Reference(vs, min_col=1, min_row=5, max_row=tr - 1))
    ch.height, ch.width = 6.5, 12
    vs.add_chart(ch, "J4")

    r0 = tr + 3
    vs.cell(r0 - 1, 1, "By category and month (top 10 categories by volume, rest grouped)").font = Font(bold=True)
    header(vs, r0, ["Category"] + months + ["Total", "% of tickets"])
    for i, cat in enumerate(categories[:10] + ["All other"]):
        r = r0 + 1 + i
        vs.cell(r, 1, cat)
        for j, mo in enumerate(months):
            c = vs.cell(r, 2 + j)
            if cat == "All other":
                top = f"{get_column_letter(2 + j)}{r0 + 1}:{get_column_letter(2 + j)}{r - 1}"
                c.value = f'=COUNTIFS(d_month,"{mo}")-SUM({top})'
            else:
                c.value = f'=COUNTIFS(d_month,"{mo}",d_category,$A{r})'
            c.number_format = INT
        tc = 2 + len(months)
        vs.cell(r, tc, f"=SUM(B{r}:{get_column_letter(tc-1)}{r})").number_format = INT
        vs.cell(r, tc + 1, f"={get_column_letter(tc)}{r}/COUNTA(d_month)").number_format = PCT
    widths(vs, [16, 11, 11, 11, 11, 13, 11, 11])

    # ---------------- Resolution & SLA ----------------
    rs = wb.create_sheet("Resolution & SLA")
    title(rs, "Resolution time and SLA",
          "Hours from opened to resolved. Medians are array formulas MEDIAN(IF(...)); SLA % = tickets with Met SLA = Yes / tickets.")
    header(rs, 4, ["Month", "Tickets", "Median hours", "Average hours", "SLA met %", "Breaches"])
    for i, mo in enumerate(months + ["All months"]):
        r = 5 + i
        rs.cell(r, 1, mo)
        cond = f"d_month=$A{r}" if mo != "All months" else 'd_month<>""'
        crit = f"d_month,$A{r}" if mo != "All months" else 'd_month,"<>"'
        rs.cell(r, 2, f"=COUNTIFS({crit})").number_format = INT
        rs[f"C{r}"] = median_if(f"C{r}", cond); rs[f"C{r}"].number_format = HRS
        rs.cell(r, 4, f"=AVERAGEIFS(d_hours,{crit})").number_format = HRS
        rs.cell(r, 5, f'=COUNTIFS({crit},d_sla,"Yes")/B{r}').number_format = PCT
        rs.cell(r, 6, f'=COUNTIFS({crit},d_sla,"No")').number_format = INT
    rs.cell(5 + len(months), 1).font = Font(bold=True)
    p0 = 5 + len(months) + 3
    rs.cell(p0 - 1, 1, "By priority").font = Font(bold=True)
    header(rs, p0, ["Priority", "Tickets", "Median hours", "Average hours", "SLA met %", "Breaches"]
           + [f"SLA % {mo}" for mo in months])
    for i, p in enumerate(priorities):
        r = p0 + 1 + i
        rs.cell(r, 1, p)
        rs.cell(r, 2, f"=COUNTIFS(d_priority,$A{r})").number_format = INT
        rs[f"C{r}"] = median_if(f"C{r}", f"d_priority=$A{r}"); rs[f"C{r}"].number_format = HRS
        rs.cell(r, 4, f"=AVERAGEIFS(d_hours,d_priority,$A{r})").number_format = HRS
        rs.cell(r, 5, f'=COUNTIFS(d_priority,$A{r},d_sla,"Yes")/B{r}').number_format = PCT
        rs.cell(r, 6, f'=COUNTIFS(d_priority,$A{r},d_sla,"No")').number_format = INT
        for j, mo in enumerate(months):
            rs.cell(r, 7 + j, f'=IFERROR(COUNTIFS(d_priority,$A{r},d_month,"{mo}",d_sla,"Yes")'
                              f'/COUNTIFS(d_priority,$A{r},d_month,"{mo}"),"")').number_format = PCT
    ch = BarChart(); ch.title = "SLA met % by priority"; ch.style = 10; ch.legend = None
    ch.add_data(Reference(rs, min_col=5, min_row=p0, max_row=p0 + 4), titles_from_data=True)
    ch.set_categories(Reference(rs, min_col=1, min_row=p0 + 1, max_row=p0 + 4))
    ch.y_axis.number_format = "0%"; ch.height, ch.width = 6.5, 12
    rs.add_chart(ch, "L4")
    widths(rs, [14, 10, 13, 13, 11, 10, 12, 12, 12])

    # ---------------- Categories (all) + Top 10 ----------------
    cs = wb.create_sheet("Categories")
    title(cs, "All categories", "Helper table for the Top 10 sheet. Tie-break column adds a tiny row-based offset so LARGE() returns unique ranks.")
    header(cs, 4, ["Category", "Tickets", "SLA breaches", "Breach rate", "Median hours", "Vol key", "Breach key"])
    for i, cat in enumerate(sorted(categories, key=lambda s: (len(s), s))):
        r = 5 + i
        cs.cell(r, 1, cat)
        cs.cell(r, 2, f"=COUNTIFS(d_category,$A{r})").number_format = INT
        cs.cell(r, 3, f'=COUNTIFS(d_category,$A{r},d_sla,"No")').number_format = INT
        cs.cell(r, 4, f"=C{r}/B{r}").number_format = PCT
        cs[f"E{r}"] = median_if(f"E{r}", f"d_category=$A{r}"); cs[f"E{r}"].number_format = HRS
        cs.cell(r, 6, f"=B{r}+ROW()/100000")
        cs.cell(r, 7, f"=C{r}+ROW()/100000")
    cl = 4 + len(categories)
    widths(cs, [16, 10, 12, 11, 12, 10, 10])

    ts = wb.create_sheet("Top 10")
    title(ts, "Top 10 categories", "Ranked with LARGE/INDEX/MATCH over the Categories sheet, so the ranking updates with the data.")
    ts["A4"] = "By ticket volume"; ts["A4"].font = Font(bold=True)
    header(ts, 5, ["Rank", "Category", "Tickets", "% of tickets", "Cumulative %", "Breach rate"])
    ts["H4"] = "By SLA breaches"; ts["H4"].font = Font(bold=True)
    header(ts, 5, ["Rank", "Category", "Breaches", "% of all breaches", "% of tickets", "Breach rate"], col=8)
    for k in range(1, 11):
        r = 5 + k
        ts.cell(r, 1, k)
        ts.cell(r, 2, f"=INDEX(Categories!$A$5:$A${cl},MATCH(LARGE(Categories!$F$5:$F${cl},A{r}),Categories!$F$5:$F${cl},0))")
        ts.cell(r, 3, f"=COUNTIFS(d_category,B{r})").number_format = INT
        ts.cell(r, 4, f"=C{r}/COUNTA(d_category)").number_format = PCT
        ts.cell(r, 5, f"=SUM($D$6:D{r})").number_format = PCT
        ts.cell(r, 6, f'=COUNTIFS(d_category,B{r},d_sla,"No")/C{r}').number_format = PCT
        ts.cell(r, 8, k)
        ts.cell(r, 9, f"=INDEX(Categories!$A$5:$A${cl},MATCH(LARGE(Categories!$G$5:$G${cl},H{r}),Categories!$G$5:$G${cl},0))")
        ts.cell(r, 10, f'=COUNTIFS(d_category,I{r},d_sla,"No")').number_format = INT
        ts.cell(r, 11, f'=J{r}/COUNTIFS(d_sla,"No")').number_format = PCT
        ts.cell(r, 12, f"=COUNTIFS(d_category,I{r})/COUNTA(d_category)").number_format = PCT
        ts.cell(r, 13, f"=J{r}/COUNTIFS(d_category,I{r})").number_format = PCT
    ch = BarChart(); ch.title = "Top 10 categories: % of tickets vs % of SLA breaches"; ch.style = 10
    ch.add_data(Reference(ts, min_col=11, max_col=12, min_row=5, max_row=15), titles_from_data=True)
    ch.set_categories(Reference(ts, min_col=9, min_row=6, max_row=15))
    ch.y_axis.number_format = "0%"; ch.height, ch.width = 7.5, 18
    ts.add_chart(ch, "A18")
    widths(ts, [6, 14, 10, 11, 12, 11, 3, 6, 14, 10, 14, 11, 11])

    # ---------------- Rates ----------------
    ra = wb.create_sheet("Reassign & Reopen")
    title(ra, "Reassignment and reopen rates",
          "Reassigned = reassignment count > 0. Reopened = reopen count > 0. Rates are share of tickets opened in the month.")
    header(ra, 4, ["Month", "Tickets", "Reassigned", "Reassignment rate", "Avg reassignments",
                   "Reopened", "Reopen rate"])
    for i, mo in enumerate(months + ["All months"]):
        r = 5 + i
        ra.cell(r, 1, mo)
        crit = f"d_month,$A{r}" if mo != "All months" else 'd_month,"<>"'
        ra.cell(r, 2, f"=COUNTIFS({crit})").number_format = INT
        ra.cell(r, 3, f'=COUNTIFS({crit},d_reassigned,"Yes")').number_format = INT
        ra.cell(r, 4, f"=C{r}/B{r}").number_format = PCT
        ra.cell(r, 5, f"=AVERAGEIFS(d_reassign,{crit})").number_format = "0.00"
        ra.cell(r, 6, f'=COUNTIFS({crit},d_reopened,"Yes")').number_format = INT
        ra.cell(r, 7, f"=F{r}/B{r}").number_format = PCT
    q0 = 5 + len(months) + 3
    ra.cell(q0 - 1, 1, "By priority").font = Font(bold=True)
    header(ra, q0, ["Priority", "Tickets", "Reassigned", "Reassignment rate", "Avg reassignments", "Reopened", "Reopen rate"])
    for i, p in enumerate(priorities):
        r = q0 + 1 + i
        ra.cell(r, 1, p)
        ra.cell(r, 2, f"=COUNTIFS(d_priority,$A{r})").number_format = INT
        ra.cell(r, 3, f'=COUNTIFS(d_priority,$A{r},d_reassigned,"Yes")').number_format = INT
        ra.cell(r, 4, f"=C{r}/B{r}").number_format = PCT
        ra.cell(r, 5, f"=AVERAGEIFS(d_reassign,d_priority,$A{r})").number_format = "0.00"
        ra.cell(r, 6, f'=COUNTIFS(d_priority,$A{r},d_reopened,"Yes")').number_format = INT
        ra.cell(r, 7, f"=F{r}/B{r}").number_format = PCT
    widths(ra, [14, 10, 11, 14, 14, 10, 11])

    # ---------------- Backlog ----------------
    bs = wb.create_sheet("Backlog")
    title(bs, "Backlog trend",
          "Open backlog at end of day = tickets opened up to that day minus tickets resolved up to that day. "
          "The extract starts empty on 1 Mar, so early-March backlog is a ramp-up, not a real dip.")
    header(bs, 4, ["Date", "Opened", "Resolved", "Open backlog (end of day)", "Month end?"])
    days = pd.date_range(months[0] + "-01", pd.Period(months[-1]).end_time.normalize(), freq="D")
    for i, d in enumerate(days):
        r = 5 + i
        bs.cell(r, 1, d.to_pydatetime()).number_format = "yyyy-mm-dd"
        bs.cell(r, 2, f'=COUNTIFS(d_opened,">="&A{r},d_opened,"<"&A{r}+1)').number_format = INT
        bs.cell(r, 3, f'=COUNTIFS(d_resolved,">="&A{r},d_resolved,"<"&A{r}+1)').number_format = INT
        bs.cell(r, 4, f'=COUNTIFS(d_opened,"<"&A{r}+1)-COUNTIFS(d_resolved,"<"&A{r}+1)').number_format = INT
        bs.cell(r, 5, "Yes" if d.is_month_end else None)
    bl = 4 + len(days)
    ch = LineChart(); ch.title = "Open backlog at end of day"; ch.style = 12; ch.legend = None
    ch.add_data(Reference(bs, min_col=4, min_row=4, max_row=bl), titles_from_data=True)
    ch.set_categories(Reference(bs, min_col=1, min_row=5, max_row=bl))
    ch.x_axis.number_format = "d mmm"; ch.height, ch.width = 7, 18
    bs.add_chart(ch, "G4")
    widths(bs, [12, 9, 9, 14, 11])

    # ---------------- Summary ----------------
    s = summary
    title(s, "IT Service Desk - Monthly Performance Summary",
          f"ServiceNow incident log (UCI dataset 498), incidents opened {m['overall']['window_label']}. "
          "All figures are formulas over the Data sheet.")
    last_mo_row = 4 + len(months)
    prev_mo_row = last_mo_row - 1
    kpis = [
        ("Tickets opened", "=COUNTA(d_month)", INT),
        ("Tickets per month (average)", f"=COUNTA(d_month)/{len(months)}", INT),
        ("SLA met %", "='Resolution & SLA'!E" + str(5 + len(months)), PCT),
        ("SLA met % - P1 Critical + P2 High", '=(COUNTIFS(d_priority,"1 - Critical",d_sla,"Yes")+COUNTIFS(d_priority,"2 - High",d_sla,"Yes"))'
                                               '/(COUNTIFS(d_priority,"1 - Critical")+COUNTIFS(d_priority,"2 - High"))', PCT),
        ("Median hours to resolve", "='Resolution & SLA'!C" + str(5 + len(months)), HRS),
        ("Average hours to resolve", "='Resolution & SLA'!D" + str(5 + len(months)), HRS),
        ("Reassignment rate", "='Reassign & Reopen'!D" + str(5 + len(months)), PCT),
        ("Reopen rate", "='Reassign & Reopen'!G" + str(5 + len(months)), PCT),
        ("Open backlog at end of period", f"=Backlog!D{bl}", INT),
        (f"Ticket volume change, {m['mom']['from_label']} to {m['mom']['to_label']}",
         f"=Volume!B{last_mo_row}/Volume!B{prev_mo_row}-1", '+0.0%;-0.0%'),
        (f"SLA % change, {m['mom']['from_label']} to {m['mom']['to_label']} (points)",
         f"=('Resolution & SLA'!E{last_mo_row}-'Resolution & SLA'!E{prev_mo_row})*100", '+0.0;-0.0'),
        ("Category with most SLA breaches", "='Top 10'!I6", "@"),
        ("  ...its share of tickets", "='Top 10'!L6", PCT),
        ("  ...its share of SLA breaches", "='Top 10'!K6", PCT),
        ("Top 5 categories' share of tickets", "='Top 10'!E10", PCT),
    ]
    header(s, 4, ["Headline", "Value"])
    for i, (label, formula, nf) in enumerate(kpis):
        r = 5 + i
        s.cell(r, 1, label).border = THIN
        c = s.cell(r, 2, formula)
        fmt(c, nf)
        c.font = Font(bold=True, size=12)
        c.alignment = Alignment(horizontal="right")
    r = 5 + len(kpis) + 1
    s.cell(r, 1, "Monthly view").font = Font(bold=True)
    header(s, r + 1, ["Month", "Tickets", "SLA met %", "Median hours", "Reassignment rate", "Reopen rate", "Backlog at month end"])
    for i, mo in enumerate(months):
        rr = r + 2 + i
        s.cell(rr, 1, mo)
        s.cell(rr, 2, f"=Volume!B{5+i}").number_format = INT
        s.cell(rr, 3, f"='Resolution & SLA'!E{5+i}").number_format = PCT
        s.cell(rr, 4, f"='Resolution & SLA'!C{5+i}").number_format = HRS
        s.cell(rr, 5, f"='Reassign & Reopen'!D{5+i}").number_format = PCT
        s.cell(rr, 6, f"='Reassign & Reopen'!G{5+i}").number_format = PCT
        me = pd.Period(mo).end_time.normalize()
        s.cell(rr, 7, f"=INDEX(Backlog!$D$5:$D${bl},MATCH(DATE({me.year},{me.month},{me.day}),Backlog!$A$5:$A${bl},0))").number_format = INT
    rn = r + 3 + len(months)
    notes = [
        "Notes",
        "- Labels in the source are anonymised (e.g. 'Category 46', 'Group 70'); names are kept as published.",
        "- SLA flag is the system's made_sla value on the final event of each incident; SLA targets are not in the data.",
        "- 94% of tickets are P3 Moderate; P1/P2 volumes are small, so their SLA % moves a lot with a few tickets.",
        "- See docs/data_notes.md for every cleaning decision.",
    ]
    for i, t in enumerate(notes):
        s.cell(rn + i, 1, t).font = Font(bold=(i == 0), size=9 if i else 11, color="52514E" if i else "000000")
    widths(s, [48, 14, 12, 13, 16, 12, 18])
    s.page_setup.orientation = "portrait"
    s.page_setup.fitToWidth = 1
    s.page_setup.fitToHeight = 1
    s.sheet_properties.pageSetUpPr.fitToPage = True

    # ---------------- Checks ----------------
    ck = wb.create_sheet("Checks")
    title(ck, "Checks: Excel formulas vs pandas", "Pandas values come from data/clean/metrics.json. Difference should be ~0.")
    header(ck, 4, ["Metric", "Excel formula", "pandas", "Difference", "OK?"])
    o = m["overall"]
    checks = [
        ("Tickets", "=Summary!B5", o["tickets"], 0.5),
        ("SLA met %", "=Summary!B7*100", o["sla_pct"], 0.051),
        ("Median hours", "=Summary!B9", o["median_res_h"], 0.051),
        ("Average hours", "=Summary!B10", o["mean_res_h"], 0.051),
        ("Reassignment rate %", "=Summary!B11*100", o["reassign_rate"], 0.051),
        ("Reopen rate %", "=Summary!B12*100", o["reopen_rate"], 0.051),
        ("Backlog at end", "=Summary!B13", m["backlog"]["end"], 0.5),
        ("Problem category breach share %", "=Summary!B18*100", m["problem"]["breach_share"], 0.051),
    ]
    for i, (lab, fx, pv, tol) in enumerate(checks):
        r = 5 + i
        ck.cell(r, 1, lab); ck.cell(r, 2, fx).number_format = "0.0"; ck.cell(r, 3, pv)
        ck.cell(r, 4, f"=B{r}-C{r}").number_format = "0.000"
        ck.cell(r, 5, f'=IF(ABS(D{r})<={tol},"OK","CHECK")')
    ck.cell(5 + len(checks), 1, "Problem category name"); ck.cell(5 + len(checks), 2, "=Summary!B16")
    ck.cell(5 + len(checks), 3, m["problem"]["category"])
    ck.cell(5 + len(checks), 5, f'=IF(B{5+len(checks)}=C{5+len(checks)},"OK","CHECK")')
    widths(ck, [32, 14, 12, 12, 8])

    wb.move_sheet("Data", offset=len(wb.sheetnames))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    return len(checks) + 1


RECALC_PS = r"""
$ErrorActionPreference = 'Stop'
$x = New-Object -ComObject Excel.Application
$x.Visible = $false; $x.DisplayAlerts = $false
try {
  $wb = $x.Workbooks.Open('{path}')
  $x.CalculateFull()
  $wb.Worksheets.Item('Summary').Activate()
  $wb.Save(); $wb.Close($false)
} finally { $x.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($x) | Out-Null }
"""


def recalc_excel():
    """Open and save the file in Excel so it carries calculated values. Skipped if Excel is absent."""
    if sys.platform != "win32":
        print("excel: recalculation skipped (Excel not available); values calculate on open")
        return False
    ps = RECALC_PS.replace("{path}", str(OUT))
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if res.returncode != 0:
        print("excel: recalculation skipped:", res.stderr.strip()[:200])
        return False
    return True


def verify(n_checks):
    from openpyxl import load_workbook
    wb = load_workbook(OUT, data_only=True)
    errors = []
    for ws in wb.worksheets:
        if ws.title == "Data":
            continue
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("#"):
                    errors.append(f"{ws.title}!{c.coordinate}={c.value}")
    ck = wb["Checks"]
    status = [ck.cell(5 + i, 5).value for i in range(n_checks)]
    if errors or any(s != "OK" for s in status):
        raise SystemExit(f"Excel check failed: errors={errors[:10]} checks={status}")
    print(f"excel: {OUT.name} recalculated in Excel, no formula errors, {n_checks}/{n_checks} checks match pandas")


def main():
    n = build()
    if recalc_excel():
        verify(n)


if __name__ == "__main__":
    main()
