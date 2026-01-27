"""
main.py
"""

import os
import json
import hmac
import hashlib
from typing import Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException

from data_ingester import IngestConfig, GitHubIngester, PrintSink

"""
    GitHub HMAC signature verification:
    - Header: X-Hub-Signature-256: sha256=<hex>
    - Compute HMAC(secret, raw_body) using SHA-256 and compare with provided hex.
"""
def _verify_github_signature(secret: str, raw_body: bytes, signature_256: Optional[str]) -> bool:
    
    # To-do:
    # For early prototyping this can be run without a secret.
    # In any real deployment, we set a webhook secret and enforce verification.
    if not secret:
        return True

    if not signature_256 or not signature_256.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_256.split("sha256=", 1)[1].strip()
    return hmac.compare_digest(expected, provided)


"""
Environment variable parsing.
"""
def _load_config() -> IngestConfig:
    github_token = os.getenv("GITHUB_TOKEN", "")
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    repo_owner = os.getenv("WATCH_REPO_OWNER", "")   # ex: "my-org"
    repo_name = os.getenv("WATCH_REPO_NAME", "")     # ex: "my-repo"

    watch_path_prefix = os.getenv("WATCH_PATH_PREFIX", "")  # ex: "services/cart"
    service_id = os.getenv("SERVICE_ID", "")

    return IngestConfig(
        github_token=github_token,
        webhook_secret=webhook_secret,
        watch_repo_owner=repo_owner,
        watch_repo_name=repo_name,
        watch_path_prefix=watch_path_prefix,
        service_id=service_id,
    )


"""
    Extracts the GitHub repository owner and repo name from a webhook payload.
"""
def _extract_repo_owner_name(payload: dict) -> Tuple[str, str]:
    repo = payload.get("repository") or {}
    owner = (repo.get("owner") or {}).get("login") or ""
    name = repo.get("name") or ""

    # Fallback: sometimes we may only have full_name
    full_name = repo.get("full_name") or ""
    if (not owner or not name) and "/" in full_name:
        owner, name = full_name.split("/", 1)

    if not owner or not name:
        raise ValueError("Missing repository.owner.login or repository.name in webhook payload")

    return owner, name


def create_app() -> FastAPI:
    load_dotenv()

    config = _load_config()
    sink = PrintSink()  # Replace later with a DB sink
    ingester = GitHubIngester(config=config, sink=sink)

    app = FastAPI(title="RootScout GitHub Webhook Receiver", version="0.1.0")
    app.state.config = config
    app.state.ingester = ingester

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        x_github_event: Optional[str] = Header(None),
        x_hub_signature_256: Optional[str] = Header(None),
    ):
        """
        Receives GitHub webhook events.
        Recommended events to enable in GitHub:
        - push
        - pull_request
        """
        raw = await request.body()

        if not _verify_github_signature(app.state.config.webhook_secret, raw, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")

        event_type = x_github_event or "unknown"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        try:
            repo_owner, repo_name = _extract_repo_owner_name(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Respond quickly and process asynchronously.
        background_tasks.add_task(app.state.ingester.handle_event, event_type, repo_owner, repo_name, payload)
        return {"accepted": True, "event_type": event_type, "repo": f"{repo_owner}/{repo_name}"}

    return app


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port_str = os.getenv("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000

    uvicorn.run("main:create_app", host=host, port=port, factory=True, reload=False)


if __name__ == "__main__":
    main()
