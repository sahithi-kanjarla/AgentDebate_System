import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.debate.service import DebateService
from app.schemas import CreateDebateRequest, CreateDebateResponse

router = APIRouter(prefix="/api/debates", tags=["debates"])


def _service(request: Request) -> DebateService:
    return request.app.state.service


@router.post("", status_code=201, response_model=CreateDebateResponse)
async def create_debate(body: CreateDebateRequest, request: Request) -> CreateDebateResponse:
    return CreateDebateResponse(id=await _service(request).start(body))


@router.get("")
async def list_debates(
    request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[dict[str, Any]]:
    return await _service(request).recent(limit)


@router.get("/{debate_id}")
async def get_debate(debate_id: str, request: Request) -> dict[str, Any]:
    debate = await _service(request).get(debate_id)
    if debate is None:
        raise HTTPException(404, "debate not found")
    return debate


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
