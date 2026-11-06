import hashlib
import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core.ratelimit import AdmissionControl, client_ip
from app.debate.service import DebateRunning, DebateService
from app.schemas import CreateDebateRequest, CreateDebateResponse

router = APIRouter(prefix="/api/debates", tags=["debates"])


_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{16,128}")


def _owner_hash(request: Request) -> str | None:
    """Hash of the X-Client-Id header, or None if it is missing or malformed. The ID itself is
    never stored or logged. It only separates one browser's History from another's; it is not
    authentication, and a debate stays readable by anyone who has its link."""
    value = request.headers.get("x-client-id", "")
    if not _CLIENT_ID.fullmatch(value):
        return None
    return hashlib.sha256(value.encode()).hexdigest()


def _service(request: Request) -> DebateService:
    return request.app.state.service


@router.post("", status_code=201, response_model=CreateDebateResponse)
async def create_debate(body: CreateDebateRequest, request: Request) -> CreateDebateResponse:
    service = _service(request)
    admission: AdmissionControl = request.app.state.admission
    ip = client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        service.settings.trusted_proxy,
    )
    # Only reads that cost nothing are free: a rerun that the response cache will answer entirely
    # skips the per-IP and global counts. The checks that need the database run only when needed.
    exempt = admission.enabled and await service.is_replayable(body)
    billable = (
        await service.billable_today(admission.now)
        if admission.needs_global_count and not exempt
        else 0
    )
    # Raises AdmissionDenied (429, handled in main.py); counts the IP only if it passes.
    admission.admit(ip=ip, exempt=exempt, running=service.running_count, billable_today=billable)
    return CreateDebateResponse(id=await service.start(body, _owner_hash(request)))


@router.get("")
async def list_debates(
    request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[dict[str, Any]]:
    return await _service(request).recent(limit, _owner_hash(request))


@router.get("/{debate_id}")
async def get_debate(debate_id: str, request: Request) -> dict[str, Any]:
    debate = await _service(request).get(debate_id)
    if debate is None:
        raise HTTPException(404, "debate not found")
    return debate


@router.get("/{debate_id}/reveal")
async def reveal_debate(debate_id: str, request: Request) -> dict[str, Any]:
    """Which provider and model answered each turn. Only for debates that are no longer running."""
    try:
        result = await _service(request).reveal(debate_id)
    except DebateRunning:
        raise HTTPException(409, "the debate is still running") from None
    if result is None:
        raise HTTPException(404, "debate not found")
    return result


@router.get("/{debate_id}/stream")
async def stream_debate(debate_id: str, request: Request) -> EventSourceResponse:
    service = _service(request)
    if not await service.exists(debate_id):
        raise HTTPException(404, "debate not found")
    last_id = request.headers.get("last-event-id", "")  # EventSource reconnects resume here
    after = int(last_id) if last_id.isdigit() else -1

    async def events():
        async for event in service.stream(debate_id, after):
            yield {"id": str(event.seq), "event": event.type, "data": json.dumps(event.data)}

    return EventSourceResponse(events())
