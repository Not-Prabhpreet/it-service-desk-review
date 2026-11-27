# IT Service Desk Performance & Problem Review

Analysis of ${overall_tickets} real ServiceNow incidents (${overall_window_label}): how the desk performed against SLA, which problem costs it the most, and what I'd change. It also includes a small working service desk built on Microsoft 365.

${try_it}

## Data

UCI "Incident management process enriched event log": ${log_raw_events} events from a company's ServiceNow instance, which I collapsed to one row per incident. Category and team names are anonymised in the source. Cleaning steps are in [data_notes.md](docs/data_notes.md).

## Findings

1. ${overall_sla_pct}% of tickets met SLA. March was the worst month at ${monthly_2016_03_sla_pct}%; April and May were ${monthly_2016_04_sla_pct}% and ${monthly_2016_05_sla_pct}%. The median ticket took ${overall_median_res_h} hours, but the average was ${overall_mean_res_h} because some tickets stay open for weeks.
2. Only ${p1p2_sla_pct}% of the ${p1p2_tickets} P1/P2 tickets met SLA. That looks more like an SLA timer setup issue than real performance, so it should be checked before anyone acts on it.
3. ${overall_reassign_rate}% of tickets were reassigned at least once. Those took a median of ${reassign_effect_med_h_yes} hours (vs ${reassign_effect_med_h_no} hours) and breached SLA ${reassign_effect_breach_yes}% of the time (vs ${reassign_effect_breach_no}%).
4. The top 5 of ${categories_count} categories make up ${categories_top5_share}% of tickets.

![Pareto of categories](docs/figures/pareto_categories.png)

## The problem I picked

${problem_category} is ${problem_share}% of tickets but ${problem_breach_share}% of SLA breaches, more than any other category. First line fixes only ${problem_first_line_share}% of it (${problem_first_line_share_rest}% for everything else), knowledge articles are used on ${problem_knowledge_rate}% of its tickets (${problem_knowledge_rate_rest}% elsewhere), and ${problem_resolver_groups} different teams end up resolving it.

What I'd do: give it one owning team, write a first-line fix and intake questions for its most common subcategory, and route it by rule instead of by guesswork. If first-line resolution got to the desk average, that's roughly ${problem_scenario_fl_breaches_avoided_pm} fewer breaches a month, and the category's breach rate would drop from ${problem_breach_rate}% to about ${problem_scenario_fl_new_cat_breach_rate}%.

Full write-up: [problem_review_rca.md](docs/problem_review_rca.md). Handling guide for these tickets: [runbook_${problem_slug}.md](docs/runbook_${problem_slug}.md).

## Dashboard

${screenshots}

## What's here

- [reports/service_desk_monthly_report.xlsx](reports/service_desk_monthly_report.xlsx): monthly Excel report, all formulas
- [powerbi/](powerbi/): Power BI project (`ServiceDesk.pbip`), `.pbix` and PDF
- [docs/](docs/): RCA, runbook, data notes
- [power-automate/](power-automate/): the live desk (form, SharePoint lists, 4 flows, exported packages, test log)

## Running it

```powershell
pip install pandas openpyxl matplotlib jsonschema pythonnet
python run_all.py
```

This rebuilds the clean data, the numbers, the Excel report, the docs and the Power BI project. If the project is open in Power BI Desktop it also refreshes it and checks every visual.
