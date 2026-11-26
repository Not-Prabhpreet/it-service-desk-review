"""Refresh the open Power BI Desktop model and test every visual's query.

Needs Power BI Desktop running with powerbi/ServiceDesk.pbip open (Windows only).
1. finds Desktop's local Analysis Services port,
2. runs a full refresh (so the CSVs in data/clean are reloaded),
3. turns each PBIR visual into an equivalent DAX query (fields, measures, visual and page
   filters) and runs it, reporting errors and empty results,
4. compares headline measures with metrics.json.
Exit code 1 on any failure. Skips cleanly (exit 0) when Desktop isn't open.
"""
import json
import sys
import time
from pathlib import Path

from config import METRICS_JSON, POWERBI_DIR

PBI_BIN = r"C:\Program Files\Microsoft Power BI Desktop\bin"
WS = Path.home() / "AppData" / "Local" / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces"
PAGES = POWERBI_DIR / "ServiceDesk.Report" / "definition" / "pages"


def connect():
    ports = sorted(WS.glob("*/Data/msmdsrv.port.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not ports:
        return None, None
    import clr  # pythonnet
    sys.path.append(PBI_BIN)
    clr.AddReference("Microsoft.PowerBI.AdomdClient")
    from Microsoft.AnalysisServices.AdomdClient import AdomdCommand, AdomdConnection
    for pf in ports:
        port = "".join(ch for ch in pf.read_bytes().decode("utf-16-le", "ignore") if ch.isdigit())
        try:
            c = AdomdConnection(f"Data Source=localhost:{port}")
            c.Open()
        except Exception:
            continue
        dbs = rows(c, AdomdCommand, "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS")
        for (db,) in dbs:
            c.ChangeDatabase(db)
            tables = [r[0] for r in rows(c, AdomdCommand, "SELECT [Name] FROM $SYSTEM.TMSCHEMA_TABLES")]
            if "Incident" in tables and "Measures" in tables:
                return c, (AdomdCommand, db)
        c.Close()
    return None, None


def rows(c, Cmd, q):
    r = Cmd(q, c).ExecuteReader()
    out = []
    while r.Read():
        out.append([r.GetValue(i) for i in range(r.FieldCount)])
    r.Close()
    return out


def ref(field):
    if "Column" in field:
        e = field["Column"]["Expression"]["SourceRef"]["Entity"]
        return f"'{e}'[{field['Column']['Property']}]", "col"
    e = field["Measure"]["Expression"]["SourceRef"]["Entity"]
    return f"[{field['Measure']['Property']}]", "measure"


def filt(f):
    cond = f["filter"]["Where"][0]["Condition"]
    target, kind = ref(f["field"])
    if "Comparison" in cond:
        op = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}[cond["Comparison"]["ComparisonKind"]]
        val = cond["Comparison"]["Right"]["Literal"]["Value"].rstrip("LD")
        return kind, target, op, val
    vals = ", ".join('"' + v[0]["Literal"]["Value"].strip("'") + '"' for v in cond["In"]["Values"])
    return kind, target, "IN", "{" + vals + "}"


def visual_query(v, page_filters):
    vis = v["visual"]
    if "query" not in vis:
        return None
    cols, meas = [], []
    for role in vis["query"]["queryState"].values():
        for p in role["projections"]:
            r, k = ref(p["field"])
            (cols if k == "col" else meas).append(r)
    col_filters, meas_filters = [], []
    for f in page_filters + v.get("filterConfig", {}).get("filters", []):
        kind, target, op, val = filt(f)
        if kind == "col":
            table = target.split("[")[0]
            expr = f"{target} IN {val}" if op == "IN" else f"{target} {op} {val}"
            col_filters.append(f"FILTER(ALL({target}), {expr})")
        else:
            meas_filters.append(f"{target} {op} {val}")
    if vis["visualType"] == "slicer":
        return f"EVALUATE TOPN(50, VALUES({cols[0]}))"
    # A measure used only as a filter is added as an extra output column so it can be filtered on.
    for mf in meas_filters:
        if mf.split(" ")[0] not in meas:
            meas.append(mf.split(" ")[0])
    named = [f'"m{i}", {m}' for i, m in enumerate(meas)]
    if cols:
        body = f"SUMMARIZECOLUMNS({', '.join(cols + col_filters + named)})"
    else:
        body = f"CALCULATETABLE(ROW({', '.join(named)}){''.join(', ' + x for x in col_filters)})"
    if meas_filters:
        conds = [f"[m{meas.index(mf.split(' ')[0])}] {mf.split(' ', 1)[1]}" for mf in meas_filters]
        body = f"FILTER({body}, {' && '.join(conds)})"
    return f"EVALUATE {body}"


def main():
    conn, info = connect()
    if conn is None:
        print("check_powerbi: Power BI Desktop is not open with this model; skipped")
        return 0
    Cmd, db = info
    t = time.time()
    Cmd(json.dumps({"refresh": {"type": "full", "objects": [{"database": db}]}}), conn).ExecuteNonQuery()
    print(f"check_powerbi: refreshed model in {time.time() - t:.1f}s")
    failures = 0
    checked = 0
    for page_dir in sorted(PAGES.iterdir()):
        if not page_dir.is_dir():
            continue
        page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
        pf = page.get("filterConfig", {}).get("filters", [])
        for vf in sorted((page_dir / "visuals").glob("*/visual.json")):
            v = json.loads(vf.read_text(encoding="utf-8"))
            q = visual_query(v, pf)
            if q is None:
                continue
            checked += 1
            try:
                res = rows(conn, Cmd, q)
                nonblank = [r for r in res if any(x is not None for x in r)]
                if not nonblank:
                    failures += 1
                    print(f"  EMPTY {page['displayName']} / {v['name']}")
            except Exception as e:
                failures += 1
                print(f"  ERROR {page['displayName']} / {v['name']}: {str(e).splitlines()[0][:300]}\n    {q[:300]}")
    m = json.loads(METRICS_JSON.read_text())
    expect = {"[Tickets]": m["overall"]["tickets"], "[SLA %]": m["overall"]["sla_pct"] / 100,
              "[Median Resolution (h)]": m["overall"]["median_res_h"], "[Reopen Rate]": m["overall"]["reopen_rate"] / 100,
              "[Reassignment Rate]": m["overall"]["reassign_rate"] / 100, "[Backlog]": m["backlog"]["end"],
              "[Repeat Rate]": m["overall"]["repeat_rate"] / 100}
    for expr, want in expect.items():
        got = rows(conn, Cmd, f'EVALUATE ROW("v", {expr})')[0][0]
        tol = 0.0006 if want < 1 else 0.051
        ok = abs(float(got) - want) <= tol
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'BAD'} {expr}: model={float(got):.4f} pandas={want}")
    conn.Close()
    print(f"check_powerbi: {checked} visual queries run, {failures} problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
