"""The 4 desk flows as Power Automate (Logic Apps) workflow definitions, built from desk_config.json.

  Desk - New ticket      Form submitted -> rules -> SharePoint ticket -> confirmation email (+ lead alert for P1/P2)
  Desk - SLA watch       every 15 min: warn assignee at 75% of SLA, escalate to lead at breach
  Desk - Resolution      ticket set to Resolved -> record resolution time + SLA result, email requester
  Desk - Daily digest    8:00 local: open tickets, backlog by priority, tickets at risk -> email lead
"""

API = "/providers/Microsoft.PowerApps/apis/"
CONNECTORS = {"sp": "shared_sharepointonline", "forms": "shared_microsoftforms", "outlook": "shared_office365"}
PRIORITIES = ["P1 Critical", "P2 High", "P3 Moderate", "P4 Low"]


def op(kind, operation, params, run_after=None, trigger_extra=None, typ="OpenApiConnection"):
    name = CONNECTORS[kind]
    a = {"type": typ, "inputs": {"host": {"connectionName": name, "operationId": operation, "apiId": API + name},
                                 "parameters": params, "authentication": "@parameters('$authentication')"}}
    if run_after is not None:
        a["runAfter"] = {r: ["Succeeded"] for r in run_after}
    if trigger_extra:
        a.update(trigger_extra)
    return a


def compose(value, after):
    return {"type": "Compose", "inputs": value, "runAfter": {a: ["Succeeded"] for a in after}}


def chain(actions):
    """Make each action run after the previous one (for actions that don't set runAfter)."""
    prev = None
    for name, a in actions.items():
        if "runAfter" not in a:
            a["runAfter"] = {prev: ["Succeeded"]} if prev else {}
        prev = name
    return actions


def email(to, subject, body, after=None, importance="Normal"):
    return op("outlook", "SendEmailV2", {"emailMessage/To": to, "emailMessage/Subject": subject,
                                         "emailMessage/Body": body, "emailMessage/Importance": importance}, after)


def wrap(triggers, actions):
    return {"$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {"$connections": {"defaultValue": {}, "type": "Object"},
                           "$authentication": {"defaultValue": {}, "type": "SecureObject"}},
            "triggers": triggers, "actions": actions}


def local(expr, tz):
    return f"convertFromUtc({expr}, '{tz}', 'ddd d MMM yyyy, HH:mm')"


STYLE = "font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2937"


def new_ticket(c):
    site, L, q, tz = c["site_url"], c["lists"], c["questions"], c["time_zone"]
    ans = lambda k: f"@outputs('Get_response_details')?['body/{q[k]}']"
    trig = {"When_a_new_response_is_submitted": op(
        "forms", "CreateFormWebhook", {"form_id": c["form_id"]}, typ="OpenApiConnectionWebhook",
        trigger_extra={"splitOn": "@triggerOutputs()?['body/value']"})}
    A = {}
    A["Get_response_details"] = op("forms", "GetFormResponseById", {
        "form_id": c["form_id"], "response_id": "@triggerOutputs()?['body/resourceData/responseId']"}, [])
    A["Answers"] = {"type": "Compose", "inputs": {k: ans(k) for k in q}}
    A["Text_to_match"] = {"type": "Compose", "inputs": "@toLower(concat(outputs('Answers')?['service'], ' ', outputs('Answers')?['description']))"}
    A["Get_keyword_rules"] = op("sp", "GetItems", {"dataset": site, "table": L["Desk Rules - Keywords"], "$top": 500})
    A["Match_keywords"] = {"type": "Query", "inputs": {"from": "@outputs('Get_keyword_rules')?['body/value']",
                                                      "where": "@contains(outputs('Text_to_match'), toLower(item()?['Title']))"}}
    A["Match_service"] = {"type": "Query", "inputs": {"from": "@outputs('Get_keyword_rules')?['body/value']",
                                                     "where": "@contains(toLower(outputs('Answers')?['service']), toLower(item()?['Title']))"}}
    A["Get_impact_rules"] = op("sp", "GetItems", {"dataset": site, "table": L["Desk Rules - Impact"], "$top": 500})
    A["Match_impact"] = {"type": "Query", "inputs": {"from": "@outputs('Get_impact_rules')?['body/value']",
                                                    "where": "@contains(outputs('Text_to_match'), toLower(item()?['Title']))"}}
    A["Match_high_impact"] = {"type": "Query", "inputs": {"from": "@body('Match_impact')",
                                                         "where": "@equals(item()?['Impact'], 'High')"}}
    # The service the requester picked wins; the description is only used when the service doesn't map.
    A["Category"] = {"type": "Compose", "inputs": "@if(not(empty(body('Match_service'))), first(body('Match_service'))?['Category'], "
                                                  "if(empty(body('Match_keywords')), 'Other', first(body('Match_keywords'))?['Category']))"}
    A["Impact"] = {"type": "Compose", "inputs": "@if(not(empty(body('Match_high_impact'))), 'High', if(empty(body('Match_impact')), 'Low', 'Medium'))"}
    A["Urgency"] = {"type": "Compose", "inputs": "@first(split(outputs('Answers')?['urgency'], ' '))"}
    A["Get_priority_rule"] = op("sp", "GetItems", {
        "dataset": site, "table": L["Desk Rules - Priority"],
        "$filter": "Impact eq '@{outputs('Impact')}' and Urgency eq '@{outputs('Urgency')}'", "$top": 1})
    A["Rule"] = {"type": "Compose", "inputs": "@first(outputs('Get_priority_rule')?['body/value'])"}
    A["Now"] = {"type": "Compose", "inputs": "@utcNow()"}
    hours = "int(outputs('Rule')?['ResolveHours'])"
    A["Create_ticket"] = op("sp", "PostItem", {
        "dataset": site, "table": L["IT Tickets"], "item/Title": "New",
        "item/RequesterName": "@outputs('Answers')?['name']", "item/RequesterEmail": "@trim(outputs('Answers')?['email'])",
        "item/Service": "@outputs('Answers')?['service']", "item/Description": "@outputs('Answers')?['description']",
        "item/Urgency/Value": "@outputs('Urgency')", "item/Impact/Value": "@outputs('Impact')",
        "item/Category": "@outputs('Category')", "item/Priority/Value": "@outputs('Rule')?['Priority']",
        "item/AssignedTo": c["default_assignee_email"], "item/Status/Value": "New",
        "item/OpenedAt": "@outputs('Now')", "item/SlaDueAt": f"@addHours(outputs('Now'), {hours})",
        "item/WarnAt": f"@addMinutes(outputs('Now'), mul({hours}, 45))",
        "item/WarnSent": False, "item/Escalated": False,
        "item/ResponseId": "@triggerOutputs()?['body/resourceData/responseId']"})
    A["Ticket_ID"] = {"type": "Compose", "inputs": "@concat('INC-', formatNumber(outputs('Create_ticket')?['body/ID'], '00000'))"}
    A["Set_ticket_ID"] = op("sp", "PatchItem", {"dataset": site, "table": L["IT Tickets"],
                                                "id": "@outputs('Create_ticket')?['body/ID']", "item/Title": "@outputs('Ticket_ID')"})
    due = local("outputs('Create_ticket')?['body/SlaDueAt']", tz)
    A["Email_requester"] = email(
        "@trim(outputs('Answers')?['email'])", "[@{outputs('Ticket_ID')}] We've received your IT request",
        f"<div style='{STYLE}'><p>Hi @{{outputs('Answers')?['name']}},</p>"
        "<p>Thanks for contacting the IT service desk. Your request is logged as <b>@{outputs('Ticket_ID')}</b>.</p>"
        "<table cellpadding='4'><tr><td>Category</td><td><b>@{outputs('Category')}</b></td></tr>"
        "<tr><td>Priority</td><td><b>@{outputs('Rule')?['Priority']}</b> (impact @{outputs('Impact')}, urgency @{outputs('Urgency')})</td></tr>"
        f"<tr><td>Target resolution</td><td><b>@{{{due}}}</b> (Newfoundland time)</td></tr></table>"
        "<p>We'll email you again when it's resolved. Reply to this email with screenshots or extra details and quote your ticket number.</p>"
        "<p>IT Service Desk (demo)</p></div>")
    A["If_P1_or_P2"] = {"type": "If", "expression": {"or": [
        {"equals": ["@outputs('Rule')?['Priority']", "P1 Critical"]},
        {"equals": ["@outputs('Rule')?['Priority']", "P2 High"]}]},
        "actions": {"Alert_lead": email(
            c["lead_email"], "HIGH PRIORITY @{outputs('Rule')?['Priority']}: @{outputs('Ticket_ID')} - @{outputs('Category')}",
            f"<div style='{STYLE}'><p><b>New @{{outputs('Rule')?['Priority']}} ticket @{{outputs('Ticket_ID')}}</b></p>"
            "<p>From: @{outputs('Answers')?['name']} (@{outputs('Answers')?['email']})<br>Service: @{outputs('Answers')?['service']}</p>"
            "<p>@{outputs('Answers')?['description']}</p>"
            f"<p>SLA due: <b>@{{{due}}}</b></p></div>", importance="High", after=[])},
        "else": {"actions": {}}}
    return wrap(trig, chain(A))


def sla_watch(c):
    site, L, tz = c["site_url"], c["lists"], c["time_zone"]
    open_f = "Status ne 'Resolved' and Status ne 'Closed'"
    trig = {"Every_15_minutes": {"type": "Recurrence", "recurrence": {"frequency": "Minute", "interval": 15}}}
    A = {}
    A["Now"] = {"type": "Compose", "inputs": "@utcNow()"}
    A["Get_near_breach"] = op("sp", "GetItems", {"dataset": site, "table": L["IT Tickets"], "$top": 500,
        "$filter": f"{open_f} and WarnSent eq 0 and WarnAt le '@{{outputs('Now')}}' and SlaDueAt gt '@{{outputs('Now')}}'"})
    it = lambda f: f"items('Warn_each')?['{f}']"
    A["Warn_each"] = {"type": "Foreach", "foreach": "@outputs('Get_near_breach')?['body/value']", "actions": chain({
        "Warn_assignee": email(f"@{it('AssignedTo')}",
                               f"SLA warning: @{{{it('Title')}}} is 75% through its SLA",
                               f"<div style='{STYLE}'><p>Ticket <b>@{{{it('Title')}}}</b> (@{{{it('Priority')}?['Value']}}, "
                               f"@{{{it('Category')}}}) will breach SLA at <b>@{{{local(it('SlaDueAt'), tz)}}}</b>.</p>"
                               f"<p>Requester: @{{{it('RequesterName')}}}<br>@{{{it('Description')}}}</p></div>", importance="High"),
        "Mark_warned": op("sp", "PatchItem", {"dataset": site, "table": L["IT Tickets"], "id": f"@{it('ID')}",
                                              "item/Title": f"@{it('Title')}", "item/WarnSent": True})})}
    A["Get_breached"] = op("sp", "GetItems", {"dataset": site, "table": L["IT Tickets"], "$top": 500,
        "$filter": f"{open_f} and Escalated eq 0 and SlaDueAt le '@{{outputs('Now')}}'"})
    ib = lambda f: f"items('Escalate_each')?['{f}']"
    A["Escalate_each"] = {"type": "Foreach", "foreach": "@outputs('Get_breached')?['body/value']", "actions": chain({
        "Escalate_to_lead": email(c["lead_email"], f"SLA BREACHED: @{{{ib('Title')}}} (@{{{ib('Priority')}?['Value']}})",
                                  f"<div style='{STYLE}'><p>Ticket <b>@{{{ib('Title')}}}</b> breached its SLA at "
                                  f"<b>@{{{local(ib('SlaDueAt'), tz)}}}</b> and is still <b>@{{{ib('Status')}?['Value']}}</b>.</p>"
                                  f"<p>Assigned to: @{{{ib('AssignedTo')}}}<br>Category: @{{{ib('Category')}}}<br>"
                                  f"Requester: @{{{ib('RequesterName')}}}</p><p>@{{{ib('Description')}}}</p></div>", importance="High"),
        "Mark_escalated": op("sp", "PatchItem", {"dataset": site, "table": L["IT Tickets"], "id": f"@{ib('ID')}",
                                                 "item/Title": f"@{ib('Title')}", "item/Escalated": True,
                                                 "item/MetSLA/Value": "No"})})}
    return wrap(trig, chain(A))


def resolution(c):
    site, L, tz = c["site_url"], c["lists"], c["time_zone"]
    t = lambda f: f"triggerOutputs()?['body/{f}']"
    trig = {"When_a_ticket_is_modified": op("sp", "GetOnUpdatedItems", {"dataset": site, "table": L["IT Tickets"]},
                                            trigger_extra={"recurrence": {"frequency": "Minute", "interval": 1},
                                                           "splitOn": "@triggerOutputs()?['body/value']"})}
    inner = chain({
        "Now": {"type": "Compose", "inputs": "@utcNow()"},
        "Hours": {"type": "Compose", "inputs": f"@div(float(sub(ticks(outputs('Now')), ticks({t('OpenedAt')}))), 36000000000.0)"},
        "Met_SLA": {"type": "Compose", "inputs": f"@if(less(ticks(outputs('Now')), ticks({t('SlaDueAt')})), 'Yes', 'No')"},
        "Record_resolution": op("sp", "PatchItem", {"dataset": site, "table": L["IT Tickets"], "id": f"@{t('ID')}",
                                                    "item/Title": f"@{t('Title')}", "item/ResolvedAt": "@outputs('Now')",
                                                    "item/ResolutionHours": "@outputs('Hours')", "item/MetSLA/Value": "@outputs('Met_SLA')"}),
        "Email_requester": email(f"@{t('RequesterEmail')}", f"[@{{{t('Title')}}}] Your IT request is resolved",
                                 f"<div style='{STYLE}'><p>Hi @{{{t('RequesterName')}}},</p>"
                                 f"<p>Your request <b>@{{{t('Title')}}}</b> has been resolved.</p>"
                                 f"<p><b>What we did:</b><br>@{{coalesce({t('ResolutionNotes')}, 'See your ticket for details.')}}</p>"
                                 "<p>Time to resolve: <b>@{formatNumber(outputs('Hours'), '0.0')} hours</b> "
                                 "(target met: @{outputs('Met_SLA')}).</p>"
                                 "<p>If the problem isn't fixed, reply within 5 days and quote your ticket number to reopen it.</p>"
                                 "<p>IT Service Desk (demo)</p></div>"),
    })
    A = {"If_newly_resolved": {"type": "If", "runAfter": {}, "expression": {"and": [
        {"equals": [f"@{t('Status/Value')}", "Resolved"]}, {"equals": [f"@empty({t('ResolvedAt')})", True]}]},
        "actions": inner, "else": {"actions": {}}}}
    return wrap(trig, A)


def daily_digest(c):
    site, L, tz = c["site_url"], c["lists"], c["time_zone"]
    trig = {"Every_day_at_8am": {"type": "Recurrence", "recurrence": {
        "frequency": "Day", "interval": 1, "timeZone": tz, "startTime": "2026-11-28T08:00:00",
        "schedule": {"hours": ["8"], "minutes": [0]}}}}
    A = {}
    A["Get_open_tickets"] = op("sp", "GetItems", {"dataset": site, "table": L["IT Tickets"], "$top": 500,
                                                 "$filter": "Status ne 'Resolved' and Status ne 'Closed'"})
    for i, p in enumerate(PRIORITIES, start=1):
        A[f"Open_P{i}"] = {"type": "Query", "inputs": {"from": "@outputs('Get_open_tickets')?['body/value']",
                                                      "where": f"@equals(item()?['Priority']?['Value'], '{p}')"}}
    A["At_risk"] = {"type": "Query", "inputs": {"from": "@outputs('Get_open_tickets')?['body/value']",
                                               "where": "@or(lessOrEquals(ticks(item()?['WarnAt']), ticks(utcNow())), lessOrEquals(ticks(item()?['SlaDueAt']), ticks(utcNow())))"}}
    A["At_risk_rows"] = {"type": "Select", "inputs": {"from": "@body('At_risk')", "select": {
        "Ticket": "@item()?['Title']", "Priority": "@item()?['Priority']?['Value']", "Status": "@item()?['Status']?['Value']",
        "Assigned to": "@item()?['AssignedTo']", "SLA due": "@" + local("item()?['SlaDueAt']", tz)}}}
    A["At_risk_table"] = {"type": "Table", "inputs": {"from": "@body('At_risk_rows')", "format": "HTML"}}
    rows = "".join(f"<tr><td>{p}</td><td><b>@{{length(body('Open_P{i}'))}}</b></td></tr>" for i, p in enumerate(PRIORITIES, 1))
    A["Email_digest"] = email(
        c["lead_email"], "IT desk daily digest: @{length(outputs('Get_open_tickets')?['body/value'])} open, @{length(body('At_risk'))} at risk",
        f"<div style='{STYLE}'><p><b>Open tickets: @{{length(outputs('Get_open_tickets')?['body/value'])}}</b></p>"
        f"<p>Backlog by priority</p><table cellpadding='4' border='1' style='border-collapse:collapse'>{rows}</table>"
        "<p>Tickets at risk (75%+ of SLA used or breached): <b>@{length(body('At_risk'))}</b></p>@{body('At_risk_table')}"
        "<p>Live list: " + c["site_url"] + "/Lists/IT%20Tickets</p></div>")
    return wrap(trig, chain(A))


FLOWS = {
    "Desk - New ticket": (new_ticket, ["sp", "forms", "outlook"]),
    "Desk - SLA watch": (sla_watch, ["sp", "outlook"]),
    "Desk - Resolution": (resolution, ["sp", "outlook"]),
    "Desk - Daily digest": (daily_digest, ["sp", "outlook"]),
}
