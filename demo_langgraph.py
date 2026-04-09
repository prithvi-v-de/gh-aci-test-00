import os
os.environ["AWS_REGION"] = "us-east-1"

import asyncio
import json
import httpx
from bedrock_agentcore.identity.auth import requires_access_token
from langgraph.graph import StateGraph, END
from typing import TypedDict


class AgentState(TypedDict):
    action: str
    result: str


# ---- GITHUB ENTERPRISE OAUTH ----
@requires_access_token(
    provider_name="afp-ghe-oauth",
    scopes=["read:user", "repo"],
    auth_flow="USER_FEDERATION",
    on_auth_url=lambda url: print(f"\n*** OPEN THIS URL FOR GITHUB ***\n{url}\n"),
    force_authentication=False,
    callback_url="http://localhost:9090/oauth2/callback",
)
async def call_github(*, access_token: str, action: str = "gh_repos"):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        if action == "gh_whoami":
            r = await client.get("https://gitprod.statestr.com/api/v3/user", headers=headers)
            return r.json() if r.status_code == 200 else {"error": r.text}
        if action == "gh_repos":
            r = await client.get(
                "https://gitprod.statestr.com/api/v3/user/repos",
                params={"per_page": 10, "sort": "updated"},
                headers=headers,
            )
            if r.status_code == 200:
                return [{"name": repo["full_name"], "url": repo["html_url"], "stars": repo["stargazers_count"]} for repo in r.json()]
            return {"error": r.text}
        if action == "gh_issues":
            r = await client.get(
                "https://gitprod.statestr.com/api/v3/issues",
                params={"per_page": 10, "state": "open"},
                headers=headers,
            )
            if r.status_code == 200:
                return [{"title": i["title"], "url": i["html_url"]} for i in r.json()]
            return {"error": r.text}
    return {"error": f"Unknown: {action}"}


# ---- ATLASSIAN OAUTH ----
@requires_access_token(
    provider_name="afp-atlassian-oauth",
    scopes=[
        "read:jira-work",
        "read:confluence-content.all",
        "read:confluence-space.summary",
        "offline_access",
    ],
    auth_flow="USER_FEDERATION",
    on_auth_url=lambda url: print(f"\n*** OPEN THIS URL FOR ATLASSIAN ***\n{url}\n"),
    force_authentication=False,
    callback_url="http://localhost:9090/oauth2/callback",
)
async def call_atlassian(*, access_token: str, action: str = "at_sites"):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        sites_resp = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers=headers,
        )
        if sites_resp.status_code != 200:
            return {"error": sites_resp.text}
        sites = sites_resp.json()
        if action == "at_sites":
            return [{"name": s.get("name"), "url": s.get("url")} for s in sites]
        # Find State Street site
        cloud_id = None
        for site in sites:
            if "statestreet" in site.get("url", ""):
                cloud_id = site["id"]
                break
        if not cloud_id:
            cloud_id = sites[0]["id"] if sites else None
        if not cloud_id:
            return {"error": "No sites found"}
        if action == "at_projects":
            r = await client.get(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project",
                headers=headers,
            )
            if r.status_code == 200:
                return [{"name": p.get("name"), "key": p.get("key")} for p in r.json()]
            return {"error": r.text}
        if action == "at_spaces":
            r = await client.get(
                f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/api/v2/spaces",
                headers=headers,
            )
            if r.status_code == 200:
                return [{"name": s.get("name"), "key": s.get("key")} for s in r.json().get("results", [])]
            return {"error": r.text}
        if action == "at_search":
            r = await client.get(
                f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/content",
                params={"limit": 10},
                headers=headers,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                return [{"title": p.get("title"), "type": p.get("type")} for p in results]
            return {"error": r.text}
    return {"error": f"Unknown: {action}"}


# ---- LANGGRAPH NODES ----
def github_node(state: AgentState) -> AgentState:
    result = asyncio.run(call_github(access_token="", action=state["action"]))
    return {"action": state["action"], "result": json.dumps(result, indent=2)}


def atlassian_node(state: AgentState) -> AgentState:
    result = asyncio.run(call_atlassian(access_token="", action=state["action"]))
    return {"action": state["action"], "result": json.dumps(result, indent=2)}


def router(state: AgentState) -> str:
    if state["action"].startswith("gh_"):
        return "github"
    elif state["action"].startswith("at_"):
        return "atlassian"
    return "github"


# ---- BUILD THE GRAPH ----
builder = StateGraph(AgentState)
builder.add_node("github", github_node)
builder.add_node("atlassian", atlassian_node)
builder.set_conditional_entry_point(router)
builder.add_edge("github", END)
builder.add_edge("atlassian", END)
graph = builder.compile()


# ---- MAIN ----
if __name__ == "__main__":
    import sys

    valid = ["gh_whoami", "gh_repos", "gh_issues", "at_sites", "at_projects", "at_spaces", "at_search"]

    if len(sys.argv) < 2:
        print(f"Usage: python demo_langgraph.py <action>")
        print(f"Actions: {', '.join(valid)}")
        sys.exit(1)

    action = sys.argv[1]
    if action not in valid:
        print(f"Invalid action. Use one of: {', '.join(valid)}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"LangGraph Agent - Action: {action}")
    print(f"{'='*50}")

    result = graph.invoke({"action": action, "result": ""})

    print(f"\n{'='*50}")
    print(f"RESULT:")
    print(f"{'='*50}")
    print(result["result"])
