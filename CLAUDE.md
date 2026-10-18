# Tribunal
Multi-agent debate system. The full spec is in @PRD.md, so read it before any work.

## Rules
- Build ONE milestone at a time (PRD section 12). Stop after each and summarize.
- Run tests and ruff before saying a milestone is done.
- All LLM model IDs live in config/agents.yaml, never hard-coded.
- Never commit .env or API keys.
- If the PRD and reality disagree (deprecated model, changed API), adapt and log it in DECISIONS.md.
- Ask me before adding any paid service or new major dependency.
- Never read, grep, print or open .env or any file containing real keys.
- Never add Co-authored-by trailers or Claude attribution to commits.
- Only commit when I ask.
- Never run anything that uses my real API keys (I run those myself).