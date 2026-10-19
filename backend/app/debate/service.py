import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.engine import Engine

from app.core.logging import debate_id_var
from app.core.ratelimit import utc_midnight
from app.core.settings import AgentsFile, Settings
from app.db import repo
from app.debate.hub import DebateChannel
from app.debate.orchestrator import Orchestrator, TurnRecord
from app.debate.prompts import PROMPTS_DIR
from app.debate.public import build_reveal, public_debate, public_event
from app.providers.base import LLMProvider
from app.providers.registry import ProviderRegistry
from app.schemas import CreateDebateRequest, DebateEvent, EventType

log = logging.getLogger(__name__)

ProviderFactory = Callable[[AgentsFile], dict[str, LLMProvider]]


class DebateRunning(Exception):
    """The reveal was requested for a debate that has not finished."""


class DebateService:
    """Starts debates in the background, persists every event, and serves replay-then-follow.

    Every DB call is synchronous SQLModel code, so it goes through `asyncio.to_thread`; the
    event loop (and therefore every SSE stream) is never blocked by SQLite.
    """

    def __init__(
        self,
        *,
        engine: Engine,
        settings: Settings,
        agents: AgentsFile,
        provider_factory: ProviderFactory,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.agents = agents
        self.provider_factory = provider_factory
        self.registry = registry
        self._channels: dict[str, DebateChannel] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    # --- lifecycle ---

    async def startup(self) -> None:
        n = await asyncio.to_thread(repo.mark_interrupted, self.engine)
        if n:
            log.warning("marked %d unfinished debate(s) as interrupted", n)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # --- commands ---

    def _fingerprint(self) -> str:
        """Hash of everything that decides the prompts and models of a debate: the agent lineup and
        the prompt files. If it matches, a repeat of the same question sends the same requests."""
        h = hashlib.sha256(self.agents.model_dump_json().encode())
        for path in sorted(PROMPTS_DIR.glob("*.md")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
        return h.hexdigest()[:16]

    def _config(self, rounds: int) -> dict[str, Any]:
        return {
            "rounds": rounds,
            "min_critique_rounds": self.settings.min_critique_rounds,
            "seed": self.settings.shuffle_seed,
            "fingerprint": self._fingerprint(),
        }

    @property
    def running_count(self) -> int:
        return len(self._channels)

    async def is_replayable(self, req: CreateDebateRequest) -> bool:
        """Would this request be answered entirely from the response cache (so it costs no
        provider calls)? Used only to decide whether it counts against the rate limits."""
        if not self.settings.cache_enabled:
            return False
        config = self._config(req.rounds or self.settings.default_rounds)
        return await asyncio.to_thread(
            repo.find_replayable, self.engine, question=req.question, mode=req.mode, config=config
        )

    async def billable_today(self, now: float) -> int:
        return await asyncio.to_thread(repo.count_billable_since, self.engine, utc_midnight(now))

    async def start(self, req: CreateDebateRequest) -> str:
        debate_id = uuid.uuid4().hex
        rounds = req.rounds or self.settings.default_rounds
        # Registered before the DB write so the concurrency cap sees it immediately.
        channel = DebateChannel()
        self._channels[debate_id] = channel
        try:
            await asyncio.to_thread(
                repo.create_debate,
                self.engine,
                debate_id=debate_id,
                question=req.question,
                mode=req.mode,
                config=self._config(rounds),
            )
        except BaseException:
            self._channels.pop(debate_id, None)
            raise
        task = asyncio.create_task(self._run(debate_id, req, rounds, channel))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return debate_id

    async def _emit(self, channel: DebateChannel, debate_id: str, type_: EventType, data: Any):
        event = DebateEvent(seq=channel.next_seq, type=type_, data=data)
        # Persist first, then publish: anything a client has seen can also be replayed from the DB.
        await asyncio.to_thread(
            repo.append_event, self.engine, debate_id, event.seq, event.type, event.data
        )
        await channel.publish(event)

    async def _run(
        self, debate_id: str, req: CreateDebateRequest, rounds: int, channel: DebateChannel
    ) -> None:
        debate_id_var.set(debate_id)
        orch: Orchestrator | None = None
        status = "completed"
        stats: dict[str, Any] | None = None
        try:
            orch = Orchestrator(
                debate_id=debate_id,
                question=req.question,
                mode=req.mode,
                rounds=rounds,
                agents=self.agents,
                providers=self.provider_factory(self.agents),
                seed=self.settings.shuffle_seed,
                min_critique_rounds=self.settings.min_critique_rounds,
            )
            async for type_, data in orch.run():
                if type_ == "done":
                    stats = data["stats"]
                await self._emit(channel, debate_id, type_, data)
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        except Exception as e:
            log.exception("debate %s failed", debate_id)
            status = "failed"
            # Always end the stream with `done` so clients stop waiting.
            await self._emit(
                channel,
                debate_id,
                "error",
                {"message": f"internal error: {e}", "recoverable": False},
            )
            stats = {
                "total_tokens": orch.stats.tokens if orch else 0,
                "latency_ms": 0,
                "calls": orch.stats.calls if orch else 0,
            }
            await self._emit(channel, debate_id, "done", {"stats": stats})
        finally:
            try:
                await asyncio.shield(
                    asyncio.to_thread(
                        repo.finish_debate,
                        self.engine,
                        debate_id,
                        status=status,
                        turns=[self._turn_row(t) for t in orch.turns] if orch else [],
                        verdict=orch.verdict.model_dump() if orch and orch.verdict else None,
                        stats=stats,
                    )
                )
            except Exception:
                log.exception("could not persist final state of debate %s", debate_id)
            await channel.finish()
            self._channels.pop(debate_id, None)

    @staticmethod
    def _turn_row(t: TurnRecord) -> dict[str, Any]:
        row = asdict(t)
        row["agent_label"] = row.pop("label")
        row.pop("error")
        return row

    # --- queries ---

    async def exists(self, debate_id: str) -> bool:
        if debate_id in self._channels:
            return True
        return await asyncio.to_thread(repo.debate_exists, self.engine, debate_id)

    async def stream(self, debate_id: str, after_seq: int = -1) -> AsyncIterator[DebateEvent]:
        """Every event after `after_seq`: those already emitted, then live ones until `done`."""
        channel = self._channels.get(debate_id)
        if channel is not None:
            async for event in channel.subscribe(after_seq + 1):
                yield public_event(event)
            return
        for row in await asyncio.to_thread(repo.get_events, self.engine, debate_id, after_seq):
            yield public_event(DebateEvent(**row))

    async def get(self, debate_id: str) -> dict[str, Any] | None:
        """The debate as the browser may see it: no provider, model or label_map."""
        debate = await asyncio.to_thread(repo.get_debate, self.engine, debate_id)
        if debate is None:
            return None
        debate["events"] = await asyncio.to_thread(repo.get_events, self.engine, debate_id)
        return public_debate(debate)

    async def reveal(self, debate_id: str) -> dict[str, Any] | None:
        """Who answered each turn. None if the debate does not exist; raises DebateRunning while
        it is still running, because the reveal is only for debates that are over."""
        if debate_id in self._channels:
            raise DebateRunning(debate_id)
        debate = await asyncio.to_thread(repo.get_debate, self.engine, debate_id)
        if debate is None:
            return None
        if debate["status"] == "running":
            raise DebateRunning(debate_id)
        return build_reveal(debate)

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(repo.list_debates, self.engine, limit)
