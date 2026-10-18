# Decisions

## M1
- **Python version:** PRD specifies 3.12; local machine has 3.13 only. `requires-python = ">=3.12"`, managed with uv. No 3.12-specific features used.
- **Project root:** repo root is the project root (no nested `tribunal/` folder); backend lives in `backend/`.
- **Review mode:** M1 carries the `mode` field and prompt plumbing only; full review mode is M5.
- **Event log:** every SSE event is persisted in order per debate (for M4 replay) and live streams replay-then-follow from that log.
- **DB access:** sync SQLModel/SQLite calls run via `asyncio.to_thread` so the event loop never blocks.
- **min_critique_rounds (default 1, env `MIN_CRITIQUE_ROUNDS`):** a debate never stops before this many critique rounds, even if round 0 is unanimous (guards against groupthink). Capped by `rounds`; 0 restores PRD-style early stop after round 0.
- **Event log table:** added `debate_event(debate_id, seq, type, data)` beyond the PRD's `Debate`/`Turn`/`CacheEntry`. SSE ids are `seq`; `Last-Event-ID` resumes after that event. Events are persisted before being published to followers.
- **Replay-then-follow:** a running debate has an in-memory `DebateChannel`; late subscribers read from position 0 and then wait for live events. Finished debates stream from the DB.
- **Startup sweep:** debates still `running` at boot are marked `interrupted`.
- **Client note for M3:** the server closes the stream after `done`; `EventSource` would auto-reconnect, so the client must close on `done`. The spec's `error` event name also collides with `EventSource.onerror` semantics; handle via `addEventListener('error')` and check `event.data`.
