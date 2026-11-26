"""Step 5: generate the Power BI Project (PBIP: TMDL semantic model + PBIR report) from code.

Power Query cannot resolve paths relative to the .pbip file, so the model reads every CSV
through one text parameter, DataFolder. This script sets it to <repo>/data/clean/ on each
run, which makes the project work wherever the repo is cloned (run `python run_all.py`).
"""
import csv
import json
import shutil
import uuid
from pathlib import Path

from config import BLUE, CLEAN_DIR, GREY, INK, INK2, ORANGE, POWERBI_DIR

NAME = "ServiceDesk"
SM = POWERBI_DIR / f"{NAME}.SemanticModel"
RP = POWERBI_DIR / f"{NAME}.Report"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VC = f"{SCHEMA}/item/report/definition/visualContainer/2.6.0/schema.json"
PAGE = f"{SCHEMA}/item/report/definition/page/2.1.0/schema.json"
BASE_THEME = "CY24SU10"
BASE_THEME_SRC = Path(r"C:\Program Files\Microsoft Power BI Desktop\bin\WebView2Resources"
                      r"\minerva\sharedresources\BaseThemes") / f"{BASE_THEME}.json"
NS = uuid.UUID("6f1c2f1e-6b1a-4d2e-9a77-2c5b1f0e9d11")


def tag(*parts):
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name):
    """Quote a TMDL/DAX object name if needed."""
    return f"'{name}'" if any(ch in name for ch in " %()-/&.") or name[0].isdigit() else name


# --------------------------------------------------------------------------------------
# Semantic model
# --------------------------------------------------------------------------------------
TYPE_M = {"string": "type text", "int64": "Int64.Type", "double": "type number",
          "dateTime": "type datetime", "date": "type date"}


def problem_config():
    with open(CLEAN_DIR / "problem_config.csv") as fh:
        return next(csv.DictReader(fh))


def tables_spec():
    pc = problem_config()
    T = {}
    T["Incident"] = dict(file="fact_incident.csv", cols=[
        ("incident_id", "string", {}), ("opened_at", "dateTime", {"fmt": "yyyy-mm-dd hh:nn"}),
        ("resolved_at", "dateTime", {"fmt": "yyyy-mm-dd hh:nn"}), ("closed_at", "dateTime", {"fmt": "yyyy-mm-dd hh:nn"}),
        ("resolved_source", "string", {}), ("priority", "string", {}), ("impact", "string", {}),
        ("urgency", "string", {}), ("category", "string", {}), ("subcategory", "string", {}),
        ("symptom", "string", {}), ("assignment_group", "string", {}), ("first_assignment_group", "string", {}),
        ("groups_touched", "int64", {}), ("caller_id", "string", {}), ("contact_type", "string", {}),
        ("location", "string", {}), ("knowledge_used", "string", {}), ("linked_problem", "string", {}),
        ("closed_code", "string", {}), ("event_count", "int64", {}), ("awaiting_user_events", "int64", {}),
        ("resolution_hours", "double", {"fmt": "#,0.0"}), ("met_sla", "string", {}), ("met_sla_flag", "int64", {}),
        ("reassignment_count", "int64", {}), ("reassigned", "string", {}), ("reopen_count", "int64", {}),
        ("reopened", "string", {}), ("opened_date", "date", {"fmt": "yyyy-mm-dd"}),
        ("resolved_date", "date", {"fmt": "yyyy-mm-dd"}), ("month", "string", {}),
        ("priority_sort", "int64", {}), ("repeat_7d", "string", {}),
        ("resolution_bucket", "string", {"sort": "resolution_bucket_sort"}), ("resolution_bucket_sort", "int64", {}),
    ])
    T["Date"] = dict(file="dim_date.csv", date_table=True, cols=[
        ("date", "date", {"fmt": "d mmm yyyy", "key": True}), ("year", "int64", {}),
        ("month", "string", {}), ("month_name", "string", {"sort": "month_sort"}),
        ("month_start", "date", {"fmt": "mmm yyyy"}), ("week_start", "date", {"fmt": "d mmm"}),
        ("weekday", "string", {}), ("month_sort", "int64", {}),
    ])
    T["Category"] = dict(file="dim_category.csv", cols=[("category", "string", {}), ("volume_rank", "int64", {})])
    T["Priority"] = dict(file="dim_priority.csv", cols=[
        ("priority", "string", {"sort": "priority_sort"}), ("priority_sort", "int64", {}),
        ("priority_short", "string", {"sort": "priority_sort"})])
    T["Assignment Group"] = dict(file="dim_assignment_group.csv", cols=[
        ("assignment_group", "string", {}), ("volume_rank", "int64", {})])
    T["Projection"] = dict(file="problem_projection.csv", cols=[
        ("metric", "string", {"sort": "metric_sort"}), ("metric_sort", "int64", {}),
        ("before", "double", {"fmt": "#,0.0"}), ("after", "double", {"fmt": "#,0.0"})])
    fl, cat = pc["first_line_group"], pc["problem_category"]
    M = [
        ("Tickets", "COUNTROWS(Incident)", "#,0"),
        ("SLA Met", 'CALCULATE([Tickets], Incident[met_sla] = "Yes")', "#,0"),
        ("SLA Breaches", 'CALCULATE([Tickets], Incident[met_sla] = "No")', "#,0"),
        ("SLA %", "DIVIDE([SLA Met], [Tickets])", "0.0%"),
        ("Breach Rate", "DIVIDE([SLA Breaches], [Tickets])", "0.0%"),
        ("Desk Breach Rate", "CALCULATE([Breach Rate], REMOVEFILTERS(Category))", "0.0%"),
        ("Median Resolution (h)", "MEDIAN(Incident[resolution_hours])", "#,0.0"),
        ("Average Resolution (h)", "AVERAGE(Incident[resolution_hours])", "#,0.0"),
        ("Reassignment Rate", "DIVIDE(CALCULATE([Tickets], Incident[reassignment_count] > 0), [Tickets])", "0.0%"),
        ("Avg Reassignments", "AVERAGE(Incident[reassignment_count])", "0.00"),
        ("Reopen Rate", "DIVIDE(CALCULATE([Tickets], Incident[reopen_count] > 0), [Tickets])", "0.0%"),
        ("Repeat Rate", 'DIVIDE(CALCULATE([Tickets], Incident[repeat_7d] = "Yes"), [Tickets])', "0.0%"),
        ("Backlog", "\nVAR d = MAX('Date'[date])\nRETURN\n    CALCULATE(\n        [Tickets],\n"
                    "        REMOVEFILTERS('Date'),\n        Incident[opened_date] <= d,\n"
                    "        ISBLANK(Incident[resolved_date]) || Incident[resolved_date] > d\n    )", "#,0"),
        ("Tickets Prev Month", "CALCULATE([Tickets], DATEADD('Date'[date], -1, MONTH))", "#,0"),
        ("Tickets MoM %", "\nVAR p = [Tickets Prev Month]\nRETURN IF(NOT ISBLANK(p), DIVIDE([Tickets] - p, p))", "+0.0%;-0.0%;0.0%"),
        ("SLA % Prev Month", "CALCULATE([SLA %], DATEADD('Date'[date], -1, MONTH))", "0.0%"),
        ("SLA % MoM (pts)", "\nVAR p = [SLA % Prev Month]\nRETURN IF(NOT ISBLANK(p), ([SLA %] - p) * 100)", "+0.0;-0.0;0.0"),
        ("Backlog MoM", "\nVAR p = CALCULATE([Backlog], DATEADD('Date'[date], -1, MONTH))\n"
                        "RETURN IF(NOT ISBLANK(p), [Backlog] - p)", "+#,0;-#,0;0"),
        ("Ticket Share", "DIVIDE([Tickets], CALCULATE([Tickets], REMOVEFILTERS(Category)))", "0.0%"),
        ("Breach Share", "DIVIDE([SLA Breaches], CALCULATE([SLA Breaches], REMOVEFILTERS(Category)))", "0.0%"),
        ("Pareto Cumulative %", "\nVAR cur = [Tickets]\nVAR tbl = ADDCOLUMNS(ALL(Category[category]), \"@t\", [Tickets])\n"
                                "VAR cum = SUMX(FILTER(tbl, [@t] >= cur), [@t])\n"
                                "RETURN IF(NOT ISBLANK(cur), DIVIDE(cum, CALCULATE([Tickets], REMOVEFILTERS(Category))))", "0.0%"),
        ("Top 5 Category Share", "\nVAR t = TOPN(5, ALL(Category[category]), [Tickets])\n"
                                 "RETURN DIVIDE(CALCULATE([Tickets], t), CALCULATE([Tickets], REMOVEFILTERS(Category)))", "0.0%"),
        ("First-line Resolution %", f'DIVIDE(CALCULATE([Tickets], Incident[assignment_group] = "{fl}"), [Tickets])', "0.0%"),
        ("Knowledge Use %", 'DIVIDE(CALCULATE([Tickets], Incident[knowledge_used] = "Yes"), [Tickets])', "0.0%"),
        ("Awaiting User %", "DIVIDE(CALCULATE([Tickets], Incident[awaiting_user_events] > 0), [Tickets])", "0.0%"),
        ("Problem Category", f'"{cat}"', None),
        ("Change", "SUM(Projection[after]) - SUM(Projection[before])", "+#,0.0;-#,0.0;0.0"),
    ]
    return T, M


def tmdl_table(name, spec):
    L = [f"table {q(name)}", f"\tlineageTag: {tag('t', name)}"]
    if spec.get("date_table"):
        L.append("\tdataCategory: Time")
    L.append("")
    for col, dt, o in spec["cols"]:
        tdt = "dateTime" if dt == "date" else dt
        L += [f"\tcolumn {q(col)}", f"\t\tdataType: {tdt}"]
        if o.get("key"):
            L.append("\t\tisKey")
        if o.get("fmt"):
            L.append(f"\t\tformatString: {o['fmt']}")
        L += [f"\t\tlineageTag: {tag('c', name, col)}",
              "\t\tsummarizeBy: none" if dt in ("string", "date", "dateTime") or col.endswith(("_sort", "_rank", "_flag", "year"))
              else "\t\tsummarizeBy: sum",
              f"\t\tsourceColumn: {col}"]
        if o.get("sort"):
            L.append(f"\t\tsortByColumn: {q(o['sort'])}")
        L += ["", "\t\tannotation SummarizationSetBy = Automatic", ""]
    types = ", ".join(f'{{"{c}", {TYPE_M[dt]}}}' for c, dt, _ in spec["cols"])
    m = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{spec["file"]}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f"    Selected = Table.SelectColumns(Promoted, {{{', '.join(chr(34) + c + chr(34) for c, _, _ in spec['cols'])}}}),",
        f'    Typed = Table.TransformColumnTypes(Selected, {{{types}}}, "en-US")',
        "in",
        "    Typed",
    ]
    L += [f"\tpartition {q(name)} = m", "\t\tmode: import", "\t\tsource ="]
    L += ["\t\t\t\t" + x for x in m]
    L += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(L)


def tmdl_measures(measures):
    L = ["table Measures", f"\tlineageTag: {tag('t', 'Measures')}", ""]
    for name, dax, fmt in measures:
        if dax.startswith("\n"):
            L.append(f"\tmeasure {q(name)} =")
            L += ["\t\t\t" + x for x in dax.strip("\n").split("\n")]
        else:
            L.append(f"\tmeasure {q(name)} = {dax}")
        if fmt:
            L.append(f"\t\tformatString: {fmt}")
        L += [f"\t\tlineageTag: {tag('m', name)}", ""]
    L += ["\tcolumn Placeholder", "\t\tdataType: string", "\t\tisHidden",
          f"\t\tlineageTag: {tag('c', 'Measures', 'Placeholder')}", "\t\tsummarizeBy: none",
          "\t\tsourceColumn: Placeholder", "", "\t\tannotation SummarizationSetBy = Automatic", "",
          "\tpartition Measures = m", "\t\tmode: import", "\t\tsource =",
          '\t\t\t\t#table(type table [Placeholder = text], {})', "",
          "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(L)


RELATIONSHIPS = [
    ("Incident", "opened_date", "Date", "date", True),
    ("Incident", "resolved_date", "Date", "date", False),
    ("Incident", "category", "Category", "category", True),
    ("Incident", "priority", "Priority", "priority", True),
    ("Incident", "assignment_group", "Assignment Group", "assignment_group", True),
]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def jwrite(path, obj):
    write(path, json.dumps(obj, indent=2) + "\n")


def build_model():
    T, M = tables_spec()
    d = SM / "definition"
    if d.exists():
        shutil.rmtree(d)
    data_folder = str(CLEAN_DIR.resolve()) + "\\"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    order = list(T) + ["Measures"]
    write(d / "model.tmdl", "\n".join([
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
        f"annotation PBI_QueryOrder = {json.dumps(['DataFolder'] + order)}", "",
        "annotation __PBI_TimeIntelligenceEnabled = 0", "",
    ] + [f"ref table {q(t)}" for t in order]) + "\n")
    write(d / "expressions.tmdl", "\n".join([
        f'expression DataFolder = "{data_folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('e', 'DataFolder')}", "", "\tannotation PBI_ResultType = Text", ""]))
    for name, spec in T.items():
        write(d / "tables" / f"{name}.tmdl", tmdl_table(name, spec))
    write(d / "tables" / "Measures.tmdl", tmdl_measures(M))
    rel = []
    for ft, fc, tt, tc, active in RELATIONSHIPS:
        rel += [f"relationship {tag('r', ft, fc, tt, tc)}"]
        if not active:
            rel.append("\tisActive: false")
        rel += [f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    write(d / "relationships.tmdl", "\n".join(rel))
    jwrite(SM / "definition.pbism", {"$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                     "version": "4.2", "settings": {}})
    jwrite(SM / ".platform", {"$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
                              "metadata": {"type": "SemanticModel", "displayName": NAME},
                              "config": {"version": "2.0", "logicalId": tag("sm")}})
    return M


# --------------------------------------------------------------------------------------
# Report helpers
# --------------------------------------------------------------------------------------
def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, int):
        s = f"{v}L"
    elif isinstance(v, float):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def color(hexv):
    return {"solid": {"color": lit(hexv)}}


def C(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def Mx(prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "Measures"}}, "Property": prop}}


def proj(field, display=None):
    k = "Column" if "Column" in field else "Measure"
    ent = field[k]["Expression"]["SourceRef"]["Entity"]
    prop = field[k]["Property"]
    p = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def where_filter(name, field, cond_builder, ftype="Advanced"):
    k = "Column" if "Column" in field else "Measure"
    ent = field[k]["Expression"]["SourceRef"]["Entity"]
    alias = ent[0].lower()
    src = {k: {"Expression": {"SourceRef": {"Source": alias}}, "Property": field[k]["Property"]}}
    return {"name": name, "field": field, "type": ftype,
            "filter": {"Version": 2, "From": [{"Name": alias, "Entity": ent, "Type": 0}],
                       "Where": [{"Condition": cond_builder(src)}]}}


def cmp_filter(name, field, kind, value):
    # ComparisonKind: 0 =, 1 >, 2 >=, 3 <, 4 <=
    return where_filter(name, field, lambda s: {"Comparison": {
        "ComparisonKind": kind, "Left": s, "Right": {"Literal": {"Value": f"{value}L"}}}})


def in_filter(name, field, values):
    return where_filter(name, field, lambda s: {"In": {
        "Expressions": [s], "Values": [[{"Literal": {"Value": "'" + v + "'"}}] for v in values]}}, "Categorical")


class Page:
    def __init__(self, name, display, order):
        self.name, self.display, self.order = name, display, order
        self.visuals, self.filters = [], []
        self.z = 0

    def add(self, vname, x, y, w, h, visual, title=None, filters=None):
        self.z += 1000
        v = {"$schema": VC, "name": vname,
             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
             "visual": visual}
        if title is not None:
            v["visual"].setdefault("visualContainerObjects", {})["title"] = [{"properties": {
                "show": lit(True), "text": lit(title), "fontSize": lit(11.0), "fontColor": color(INK), "bold": lit(True)}}]
        if filters:
            v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)


def chart(vtype, roles, sort=None, objects=None, drill=True):
    vis = {"visualType": vtype,
           "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}},
           "drillFilterOtherVisuals": drill}
    if sort:
        vis["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort],
                                          "isDefaultSort": False}
    if objects:
        vis["objects"] = objects
    return vis


def card(measure, label):
    return chart("card", {"Values": [proj(Mx(measure), label)]}, objects={
        "labels": [{"properties": {"fontSize": lit(22.0), "color": color(INK)}}],
        "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(10.0), "color": color(INK2)}}],
    })


def textbox(runs):
    paras = []
    for text, size, bold, col in runs:
        paras.append({"textRuns": [{"value": text, "textStyle": {
            "fontSize": f"{size}pt", "fontWeight": "bold" if bold else "normal", "color": col}}]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paras}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": lit(False)}}],
                                       "border": [{"properties": {"show": lit(False)}}]}}


def slicer(field, group, label):
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj(field, label)]}}},
            "objects": {"data": [{"properties": {"mode": lit("Dropdown")}}],
                        "header": [{"properties": {"show": lit(True), "text": lit(label), "fontColor": color(INK2)}}]},
            "syncGroup": {"groupName": group, "fieldChanges": True, "filterChanges": True},
            "drillFilterOtherVisuals": True}


def bar_color(hexv):
    return {"dataPoint": [{"properties": {"fill": color(hexv)}}]}


def page_header(p, title, subtitle):
    p.add("header", 24, 8, 690, 62, textbox([(title, 20, True, "#1F3A5F"), (subtitle, 10, False, INK2)]))
    p.add("slicerMonth", 726, 12, 170, 58, slicer(C("Date", "month_name"), "month", "Month"))
    p.add("slicerPriority", 906, 12, 170, 58, slicer(C("Priority", "priority_short"), "priority", "Priority"))
    p.add("slicerGroup", 1086, 12, 170, 58, slicer(C("Assignment Group", "assignment_group"), "group", "Assignment group"))


def build_pages(metrics):
    pc = metrics["problem"]["category"]
    fl = metrics["first_line"]["group"]
    pages = []
    cat, grp = C("Category", "category"), C("Assignment Group", "assignment_group")

    # 1. Service Overview -----------------------------------------------------------------
    p = Page("serviceOverview", "Service Overview", 0)
    page_header(p, "Service Overview", f"ServiceNow incidents opened {metrics['overall']['window_label']} · UCI dataset 498")
    kpis = [("Tickets", "Tickets"), ("SLA %", "SLA met %"), ("Median Resolution (h)", "Median hours to resolve"),
            ("Reassignment Rate", "Reassignment rate"), ("Reopen Rate", "Reopen rate"), ("Backlog", "Open backlog (end of period)")]
    for i, (mname, label) in enumerate(kpis):
        p.add(f"kpi{i}", 24 + i * 207, 80, 195, 100, card(mname, label))
    p.add("volumeTrend", 24, 192, 610, 250,
          chart("clusteredColumnChart", {"Category": [proj(C("Date", "week_start"), "Week starting")],
                                         "Y": [proj(Mx("Tickets"))]}, objects=bar_color(BLUE)),
          title="Tickets opened per week")
    p.add("slaTrend", 646, 192, 610, 250,
          chart("lineChart", {"Category": [proj(C("Date", "week_start"), "Week starting")],
                              "Y": [proj(Mx("SLA %"))]},
                objects={"dataPoint": [{"properties": {"fill": color(BLUE)}}],
                         "valueAxis": [{"properties": {"start": lit(0.0), "end": lit(1.0)}}]}),
          title="SLA met % by week opened")
    p.add("prioritySplit", 24, 454, 400, 254,
          chart("clusteredBarChart", {"Category": [proj(C("Priority", "priority_short"), "Priority")],
                                      "Y": [proj(Mx("Tickets"))]},
                sort=[(C("Priority", "priority_short"), "Ascending")],
                objects={**bar_color(BLUE), "labels": [{"properties": {"show": lit(True)}}]}),
          title="Tickets by priority")
    p.add("monthlyTable", 436, 454, 820, 254,
          chart("tableEx", {"Values": [proj(C("Date", "month_name"), "Month"), proj(Mx("Tickets")),
                                       proj(Mx("Tickets MoM %"), "Tickets MoM"), proj(Mx("SLA %"), "SLA met %"),
                                       proj(Mx("SLA % MoM (pts)"), "SLA MoM (pts)"),
                                       proj(Mx("Median Resolution (h)"), "Median h"),
                                       proj(Mx("Backlog"), "Backlog at month end"), proj(Mx("Backlog MoM"), "Backlog MoM")]},
                sort=[(C("Date", "month_name"), "Ascending")]),
          title="Month by month (MoM = change from previous month)")
    pages.append(p)

    # 2. SLA & Resolution -----------------------------------------------------------------
    p = Page("slaResolution", "SLA & Resolution", 1)
    page_header(p, "SLA & Resolution", "How often SLAs are met, how long tickets take, and where they stall")
    p.add("slaByPriority", 24, 80, 400, 300,
          chart("clusteredBarChart", {"Category": [proj(C("Priority", "priority_short"), "Priority")],
                                      "Y": [proj(Mx("SLA %"), "SLA met %")]},
                sort=[(C("Priority", "priority_short"), "Ascending")],
                objects={**bar_color(BLUE), "labels": [{"properties": {"show": lit(True)}}]}),
          title="SLA met % by priority")
    p.add("slaByCategory", 436, 80, 400, 300,
          chart("clusteredBarChart", {"Category": [proj(cat, "Category")], "Y": [proj(Mx("SLA %"), "SLA met %")]},
                sort=[(Mx("SLA %"), "Ascending")],
                objects={**bar_color(BLUE), "labels": [{"properties": {"show": lit(True)}}]}),
          title="SLA met % - top 10 categories by volume",
          filters=[cmp_filter("top10cat", C("Category", "volume_rank"), 4, 10)])
    p.add("resolutionDist", 848, 80, 408, 300,
          chart("clusteredColumnChart", {"Category": [proj(C("Incident", "resolution_bucket"), "Time to resolve")],
                                         "Y": [proj(Mx("Tickets"))]},
                sort=[(C("Incident", "resolution_bucket"), "Ascending")],
                objects={**bar_color(BLUE), "labels": [{"properties": {"show": lit(True)}}]}),
          title="Resolution time distribution")
    p.add("worstGroups", 24, 392, 700, 316,
          chart("tableEx", {"Values": [proj(grp, "Assignment group"), proj(Mx("Tickets")), proj(Mx("SLA %"), "SLA met %"),
                                       proj(Mx("Median Resolution (h)"), "Median h"),
                                       proj(Mx("Reassignment Rate"), "Reassigned"), proj(Mx("Reopen Rate"), "Reopened")]},
                sort=[(Mx("SLA %"), "Ascending")]),
          title="Worst-performing groups (100+ tickets), lowest SLA first",
          filters=[cmp_filter("min100", Mx("Tickets"), 2, 100)])
    p.add("medianByWeek", 736, 392, 520, 316,
          chart("lineChart", {"Category": [proj(C("Date", "week_start"), "Week starting")],
                              "Y": [proj(Mx("Median Resolution (h)"), "Median hours")]},
                objects={"dataPoint": [{"properties": {"fill": color(BLUE)}}]}),
          title="Median hours to resolve, by week opened")
    pages.append(p)

    # 3. Recurring Issues -----------------------------------------------------------------
    p = Page("recurringIssues", "Recurring Issues", 2)
    page_header(p, "Recurring Issues", "Which categories drive the volume, the breaches and the repeat contacts")
    for i, (mname, label) in enumerate([("Top 5 Category Share", "Top 5 categories' share of tickets"),
                                        ("Repeat Rate", "Repeat tickets (same caller + category, 7 days)"),
                                        ("Reopen Rate", "Reopen rate"), ("Reassignment Rate", "Reassignment rate")]):
        p.add(f"kpi{i}", 24 + i * 311, 80, 299, 100, card(mname, label))
    p.add("pareto", 24, 192, 820, 300,
          chart("lineClusteredColumnComboChart",
                {"Category": [proj(cat, "Category")], "Y": [proj(Mx("Ticket Share"), "% of tickets")],
                 "Y2": [proj(Mx("Pareto Cumulative %"), "Cumulative %")]},
                sort=[(Mx("Ticket Share"), "Descending")],
                objects={"dataPoint": [{"properties": {"fill": color(BLUE)}}],
                         "valueAxis": [{"properties": {"start": lit(0.0), "end": lit(1.0), "secShow": lit(False)}}]}),
          title="Pareto: share of tickets by category and cumulative share (top 15 categories)",
          filters=[cmp_filter("top15", C("Category", "volume_rank"), 4, 15)])
    p.add("topBreaches", 856, 192, 400, 300,
          chart("clusteredBarChart", {"Category": [proj(cat, "Category")], "Y": [proj(Mx("SLA Breaches"))]},
                sort=[(Mx("SLA Breaches"), "Descending")],
                objects={**bar_color(ORANGE), "labels": [{"properties": {"show": lit(True)}}]}),
          title="Top drivers of SLA breaches (top 10 categories by volume)",
          filters=[cmp_filter("top10", C("Category", "volume_rank"), 4, 10)])
    p.add("repeatTable", 24, 504, 1232, 204,
          chart("tableEx", {"Values": [proj(cat, "Category"), proj(Mx("Tickets")), proj(Mx("Ticket Share"), "% of tickets"),
                                       proj(Mx("Breach Share"), "% of breaches"), proj(Mx("Repeat Rate"), "Repeat tickets"),
                                       proj(Mx("Reopen Rate"), "Reopened"), proj(Mx("Reassignment Rate"), "Reassigned"),
                                       proj(Mx("Knowledge Use %"), "Knowledge used")]},
                sort=[(Mx("Tickets"), "Descending")]),
          title="Repeat and reopened tickets by category (top 10 by volume)",
          filters=[cmp_filter("top10t", C("Category", "volume_rank"), 4, 10)])
    pages.append(p)

    # 4. Problem Review ---------------------------------------------------------------------
    pr = metrics["problem"]
    sc = metrics["problem_scenario_fl"]
    p = Page("problemReview", "Problem Review", 3)
    page_header(p, f"Problem Review: {pc}",
                f"Largest source of SLA breaches · first line = {fl} · page filtered to {pc}")
    p.filters.append(in_filter("problemCategory", cat, [pc]))
    for i, (mname, label) in enumerate([("Ticket Share", "Share of all tickets"), ("Breach Share", "Share of all SLA breaches"),
                                        ("Breach Rate", "Breach rate"), ("First-line Resolution %", f"Resolved by first line ({fl})"),
                                        ("Median Resolution (h)", "Median hours to resolve"), ("Repeat Rate", "Repeat tickets")]):
        p.add(f"kpi{i}", 24 + i * 207, 80, 195, 100, card(mname, label))
    p.add("trend", 24, 192, 610, 260,
          chart("lineChart", {"Category": [proj(C("Date", "week_start"), "Week starting")],
                              "Y": [proj(Mx("Breach Rate"), f"{pc} breach rate"),
                                    proj(Mx("Desk Breach Rate"), "Whole desk breach rate")]},
                objects={"dataPoint": [{"selector": {"metadata": "Measures.Breach Rate"}, "properties": {"fill": color(ORANGE)}},
                                       {"selector": {"metadata": "Measures.Desk Breach Rate"}, "properties": {"fill": color(GREY)}}],
                         "valueAxis": [{"properties": {"start": lit(0.0), "end": lit(1.0)}}]}),
          title=f"Trend: {pc} breach rate vs whole desk, by week opened")
    p.add("groups", 646, 192, 610, 260,
          chart("tableEx", {"Values": [proj(grp, "Resolving group"), proj(Mx("Tickets")),
                                       proj(Mx("Median Resolution (h)"), "Median h"), proj(Mx("Breach Rate"), "Breach rate"),
                                       proj(Mx("Reassignment Rate"), "Reassigned")]},
                sort=[(Mx("Tickets"), "Descending")]),
          title=f"Impact: who resolves {pc} and how fast")
    p.add("projection", 24, 464, 610, 244,
          chart("tableEx", {"Values": [proj(C("Projection", "metric"), "Measure"),
                                       proj(C("Projection", "before"), "Before"),
                                       proj(C("Projection", "after"), "After (projected)"), proj(Mx("Change"))]},
                sort=[(C("Projection", "metric"), "Ascending")]),
          title=f"Before / after: {pc} first-line resolution raised to the desk rate ({sc['target_share']}%)")
    p.add("recommendation", 646, 464, 610, 244, textbox([
        ("Recommendation", 12, True, "#1F3A5F"),
        (f"{pc} is {pr['share']}% of tickets but {pr['breach_share']}% of SLA breaches. Only "
         f"{pr['first_line_share']}% is fixed at first line (desk: {pr['first_line_share_rest']}%), "
         f"knowledge is attached on {pr['knowledge_rate']}% (desk: {pr['knowledge_rate_rest']}%) and "
         f"{pr['resolver_groups']} different groups resolve it.", 10, False, INK),
        ("Quick wins: first-line knowledge article for the top subcategory, mandatory intake questions, "
         "rule-based routing to one second-line group.", 10, False, INK),
        (f"Expected: about {sc['breaches_avoided_pm']} fewer breaches and about {sc['hours_saved_pm']:,} fewer customer-wait "
         f"hours a month. See docs/problem_review_rca.md.", 10, False, INK),
    ]))
    pages.append(p)
    return pages


def theme():
    return {"name": "ServiceDesk",
            "dataColors": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
            "foreground": INK, "foregroundNeutralSecondary": INK2, "background": "#FFFFFF",
            "tableAccent": "#2a78d6", "good": "#008300", "neutral": "#eda100", "bad": "#e34948",
            "textClasses": {"label": {"fontFace": "Segoe UI", "fontSize": 9, "color": INK2},
                            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": INK},
                            "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 22, "color": INK}},
            "visualStyles": {
                "*": {"*": {"background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
                            "border": [{"show": True, "color": {"solid": {"color": "#E6E4DF"}}, "radius": 6}],
                            "dropShadow": [{"show": False}],
                            "visualHeader": [{"show": True}]}},
                "page": {"*": {"background": [{"color": {"solid": {"color": "#F5F4F0"}}, "transparency": 0}]}}}}


def build_report(metrics, extra_pages=()):
    d = RP / "definition"
    if RP.exists():
        shutil.rmtree(RP)
    pages = build_pages(metrics) + list(extra_pages)
    ver = {"visual": "2.6.0", "report": "3.0.0", "page": "2.1.0"}
    jwrite(d / "version.json", {"$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
                                "version": "2.0.0"})
    jwrite(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": ver, "type": "SharedResources"},
            "customTheme": {"name": "ServiceDesk.json", "reportVersionAtImport": ver, "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "ServiceDesk.json", "path": "ServiceDesk.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True},
    })
    jwrite(d / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name})
    for p in pages:
        pj = {"$schema": PAGE, "name": p.name, "displayName": p.display, "displayOption": "FitToPage",
              "height": 720, "width": 1280}
        if p.filters:
            pj["filterConfig"] = {"filters": p.filters}
        jwrite(d / "pages" / p.name / "page.json", pj)
        for v in p.visuals:
            jwrite(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)
    sr = RP / "StaticResources"
    jwrite(sr / "RegisteredResources" / "ServiceDesk.json", theme())
    if BASE_THEME_SRC.exists():
        (sr / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
        shutil.copy(BASE_THEME_SRC, sr / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json")
    jwrite(RP / "definition.pbir", {"$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
                                    "version": "4.0",
                                    "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    jwrite(RP / ".platform", {"$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
                              "metadata": {"type": "Report", "displayName": NAME},
                              "config": {"version": "2.0", "logicalId": tag("rp")}})
    jwrite(POWERBI_DIR / f"{NAME}.pbip", {"$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
                                          "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                          "settings": {"enableAutoRecovery": True}})
    write(POWERBI_DIR / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    return pages


def main():
    from config import METRICS_JSON
    metrics = json.loads(METRICS_JSON.read_text())
    build_model()
    pages = build_report(metrics)
    n = sum(len(p.visuals) for p in pages)
    print(f"pbip: {NAME}.pbip with {len(pages)} pages / {n} visuals; DataFolder = {CLEAN_DIR.resolve()}")


if __name__ == "__main__":
    main()
