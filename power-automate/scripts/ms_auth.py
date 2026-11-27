"""Device-code sign-in for the setup scripts (Microsoft Graph and Power Automate APIs).

Uses Microsoft's own public client apps, so no app registration is needed:
  - Graph: "Microsoft Graph Command Line Tools" (the app behind Connect-MgGraph)
  - Power Automate: "Microsoft Azure PowerShell" (the app behind Add-PowerAppsAccount)
The token cache is kept outside the repo (~/.cache/service-desk-auth) and never committed.
"""
import json
import sys
from pathlib import Path

import msal

CONFIG = Path(__file__).resolve().parents[1] / "desk_config.json"
CACHE = Path.home() / ".cache" / "service-desk-auth" / "token_cache.json"
CLIENTS = {
    "graph": ("14d82eec-204b-4c2f-b7e8-296a70dab67e",
              ["https://graph.microsoft.com/Sites.Manage.All", "https://graph.microsoft.com/User.Read"]),
    "flow": ("1950a258-227b-4e31-a9cf-717495945fc2", ["https://service.flow.microsoft.com//.default"]),
    "powerapps": ("1950a258-227b-4e31-a9cf-717495945fc2", ["https://service.powerapps.com//.default"]),
}


def config():
    return json.loads(CONFIG.read_text())


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


def token(kind):
    cfg = config()
    client_id, scopes = CLIENTS[kind]
    cache = msal.SerializableTokenCache()
    if CACHE.exists():
        cache.deserialize(CACHE.read_text())
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{cfg['tenant_id']}",
                                       token_cache=cache)
    result = None
    for acct in app.get_accounts(username=cfg["account"]):
        result = app.acquire_token_silent(scopes, account=acct)
        if result:
            break
    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        print(f"DEVICE_CODE {flow['user_code']} at {flow['verification_uri']}", flush=True)
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error_description', result)}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(cache.serialize())
    return result["access_token"]
