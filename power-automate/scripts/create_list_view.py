"""Add a compact 'Desk view' to the IT Tickets list and make it the default (SharePoint REST)."""
import msal
import requests

from ms_auth import CACHE, CLIENTS, config

FIELDS = ["LinkTitle", "Category", "Priority", "Status", "OpenedAt", "SlaDueAt", "MetSLA",
          "ResolutionHours", "RequesterName"]


def sp_token(site):
    cfg = config()
    cache = msal.SerializableTokenCache()
    cache.deserialize(CACHE.read_text())
    app = msal.PublicClientApplication(CLIENTS["graph"][0], token_cache=cache,
                                       authority=f"https://login.microsoftonline.com/{cfg['tenant_id']}")
    acct = app.get_accounts(username=cfg["account"])[0]
    return app.acquire_token_silent([f"{site}/.default"], account=acct)["access_token"]


def main():
    c = config()
    site = c["site_url"]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {sp_token(site)}", "Accept": "application/json;odata=verbose",
                      "Content-Type": "application/json;odata=verbose"})
    lst = f"{site}/_api/web/lists(guid'{c['lists']['IT Tickets']}')"
    views = {v["Title"]: v["Id"] for v in s.get(f"{lst}/views").json()["d"]["results"]}
    if "Desk view" in views:  # recreate so field changes apply
        s.post(f"{lst}/views('{views['Desk view']}')", headers={"X-HTTP-Method": "DELETE", "IF-MATCH": "*"}).raise_for_status()
    body = {"parameters": {"__metadata": {"type": "SP.ViewCreationInformation"}, "Title": "Desk view",
                           "SetAsDefaultView": True, "PersonalView": False, "RowLimit": 100,
                           "ViewFields": {"__metadata": {"type": "Collection(Edm.String)"}, "results": FIELDS},
                           "Query": '<OrderBy><FieldRef Name="ID" Ascending="FALSE"/></OrderBy>'}}
    r = s.post(f"{lst}/views/add", json=body)
    r.raise_for_status()
    print("created Desk view (default)")


if __name__ == "__main__":
    main()
