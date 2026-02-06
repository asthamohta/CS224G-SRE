"""
main.py
"""

import asyncio
import os
import json
import hmac
import hashlib
from typing import Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, Header, HTTPException, Response

# GitHub ingestion
from RootScout.github_ingester import FileAppendSink, IngestConfig, GitHubIngester, PrintSink as GitHubPrintSink

# OTel ingestion (you created this in otel_ingester.py)
from RootScout.otel_ingester import OTelIngester, PrintSink as OTelPrintSink

# OTLP protobuf messages (from opentelemetry-proto)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)

PROTO_CT = "application/x-protobuf"


"""
GitHub HMAC signature verification:
- Header: X-Hub-Signature-256: sha256=<hex>
- Compute HMAC(secret, raw_body) using SHA-256 and compare with provided hex.
"""
def _verify_github_signature(secret: str, raw_body: bytes, signature_256: Optional[str]) -> bool:
    if not secret:
        return True

    if not signature_256 or not signature_256.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_256.split("sha256=", 1)[1].strip()
    return hmac.compare_digest(expected, provided)


"""
Environment variable parsing for GitHub ingestion.
"""
def _load_config() -> IngestConfig:
    github_token = os.getenv("GITHUB_TOKEN", "")
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    repo_owner = os.getenv("WATCH_REPO_OWNER", "")
    repo_name = os.getenv("WATCH_REPO_NAME", "")

    watch_path_prefix = os.getenv("WATCH_PATH_PREFIX", "")
    service_id = os.getenv("SERVICE_ID", "")
    github_output_path = os.getenv("GITHUB_OUTPUT_PATH", "").strip()

    return IngestConfig(
        github_token=github_token,
        webhook_secret=webhook_secret,
        watch_repo_owner=repo_owner,
        watch_repo_name=repo_name,
        watch_path_prefix=watch_path_prefix,
        service_id=service_id,
        github_output_path=github_output_path,
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


def _parse_protobuf(msg, raw: bytes):
    try:
        msg.ParseFromString(raw)
        return msg
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid protobuf payload: {e}")


def create_app() -> FastAPI:
    load_dotenv()

    # GitHub ingestion setup
    config = _load_config()

    if config.github_output_path:
        print(f"[config] Writing GitHub change events to file: {config.github_output_path}")
        gh_sink = FileAppendSink(output_path=config.github_output_path, also_print=False)
    else:
        print("[config] GITHUB_OUTPUT_PATH not set; GitHub change events will be printed to console only")
        gh_sink = GitHubPrintSink()

    gh_ingester = GitHubIngester(config=config, sink=gh_sink)

    # OTel ingestion setup
    otel_sink = OTelPrintSink()  # Replace later with a DB sink
    otel_ingester = OTelIngester(sink=otel_sink)

    app = FastAPI(title="RootScout Ingestion Service", version="0.2.0")
    app.state.config = config
    app.state.gh_ingester = gh_ingester
    app.state.otel_ingester = otel_ingester

    @app.get("/healthz")
    def healthz():
        return {"ok": True}
    
    @app.on_event("startup")
    async def _startup_backfill():
        owner = app.state.config.watch_repo_owner
        repo = app.state.config.watch_repo_name
        print(f"[startup] WATCH_REPO_OWNER={owner} WATCH_REPO_NAME={repo}")
        if owner and repo:
            print("[startup] scheduling PR backfill...")
            asyncio.create_task(app.state.gh_ingester.backfill_pull_requests(owner, repo))
        else:
            print("[startup] skipping backfill, missing owner/repo env vars")


    # -------------------------
    # GitHub webhook endpoint
    # -------------------------
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
        background_tasks.add_task(app.state.gh_ingester.handle_event, event_type, repo_owner, repo_name, payload)
        return {"accepted": True, "event_type": event_type, "repo": f"{repo_owner}/{repo_name}"}

    # -------------------------
    # OTLP HTTP endpoints
    # -------------------------
    @app.post("/v1/traces")
    async def otlp_traces(request: Request, content_type: Optional[str] = Header(None)):
        raw = await request.body()
        req = _parse_protobuf(ExportTraceServiceRequest(), raw)

        # Ingest synchronously (fast) or move to background if needed later
        result = app.state.otel_ingester.ingest_traces(req)

        resp = ExportTraceServiceResponse()
        ct = content_type or PROTO_CT
        return Response(
            content=resp.SerializeToString(),
            media_type=ct,
            headers={"X-RootScout-Count": str(result.count)},
        )

    @app.post("/v1/metrics")
    async def otlp_metrics(request: Request, content_type: Optional[str] = Header(None)):
        raw = await request.body()
        req = _parse_protobuf(ExportMetricsServiceRequest(), raw)

        result = app.state.otel_ingester.ingest_metrics(req)

        resp = ExportMetricsServiceResponse()
        ct = content_type or PROTO_CT
        return Response(
            content=resp.SerializeToString(),
            media_type=ct,
            headers={"X-RootScout-Count": str(result.count)},
        )

    @app.post("/v1/logs")
    async def otlp_logs(request: Request, content_type: Optional[str] = Header(None)):
        raw = await request.body()
        req = _parse_protobuf(ExportLogsServiceRequest(), raw)

        result = app.state.otel_ingester.ingest_logs(req)

        resp = ExportLogsServiceResponse()
        ct = content_type or PROTO_CT
        return Response(
            content=resp.SerializeToString(),
            media_type=ct,
            headers={"X-RootScout-Count": str(result.count)},
        )

    return app


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port_str = os.getenv("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000

    uvicorn.run("RootScout.main:create_app", host=host, port=port, factory=True, reload=False)


if __name__ == "__main__":
    main()