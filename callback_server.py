import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from bedrock_agentcore.services.identity import IdentityClient, UserIdIdentifier

app = FastAPI()
identity_client = IdentityClient(region="us-east-1")

@app.get("/ping")
async def ping():
    return {"status": "success"}

@app.get("/oauth2/callback")
async def callback(session_id: str):
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    print(f"Session binding: user=1ec54af7, session={session_id}")

    identity_client.complete_resource_token_auth(
        session_uri=session_id,
        user_identifier=UserIdIdentifier(user_id="0499c254"),
    )

    return HTMLResponse(content="<h1>OAuth2 Success! You can close this tab.</h1>")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9090)
