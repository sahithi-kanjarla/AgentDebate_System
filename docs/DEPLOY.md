# Deploying Tribunal

One container serves the API and the built frontend on port 7860 (what Hugging Face Spaces, Docker
SDK, expects). This file covers building and testing the image, the Space setup, the checks to
run after a deploy, and the [pre-deploy checklist](#pre-deploy-checklist) to complete before the
Space is made public.

## What is in the image

`backend/app`, `backend/config` (both agent configs) and the built `frontend/dist` (which includes
`dist/showcase`, the recorded examples). Nothing else: no `.env`, no tests, no eval data, no git
history. It runs as uid 1000 (`user`) with one uvicorn worker. Expected size: about 250 to 300 MB on
disk, about 90 to 110 MB compressed (an estimate until you run `docker images`).

## Environment variables

Baked into the image as defaults (a Space *variable* with the same name overrides them):

| Variable | Image default | Meaning |
|---|---|---|
| `FRONTEND_DIST` | `/app/frontend/dist` | Folder of the built frontend the API serves |
| `DATABASE_URL` | `sqlite:////home/user/data/tribunal.db` | Debate history. Ephemeral on Spaces |
| `AGENTS_CONFIG` | `/app/backend/config/agents.yaml` | Real lineup. `config/agents.mock.yaml` = offline mock |
| `RATE_LIMIT_ENABLED` | `true` | Per-IP and global limits. Leave on |
| `RATE_LIMIT_PER_HOUR` / `RATE_LIMIT_PER_DAY` | `5` / `20` | Debates per IP |
| `GLOBAL_DAILY_CAP` | `15` | Real debates per UTC day, all visitors (`0` = off) |
| `MAX_CONCURRENT_DEBATES` | `3` | Debates running at once (`0` = off) |
| `TRUSTED_PROXY` | `1` | Proxies in front of the app (see "Client IP" below) |
| `EXPOSE_AGENT_MODELS` | `false` | Must stay `false`: `true` un-anonymizes every debate |
| `CACHE_ENABLED` | `true` | Response cache (also ephemeral) |
| `LOG_LEVEL` | `INFO` | |

Space **Secrets** (never in the image, git or a Variable):
`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`. A blank or missing key
disables that provider, and the debate falls through its fallback chain. The first log lines say
which providers have a key (names only) and whether rate limiting is ON.

Build argument: `SHOWCASE_STRICT` (default `1`). With `1` the frontend build **fails** while any
test-only placeholder file is in `frontend/public/showcase`; `0` only warns. Use `0` for a local or
private test while the placeholders are still there; never for the public Space.

## What is lost on a restart

Spaces storage is ephemeral. After every restart, rebuild or wake from sleep:

- the SQLite database is empty: the History page, every `/debate/{id}` share link and the stored
  event logs are gone;
- History is per browser (an `X-Client-Id` header; the server stores only its hash as `owner_hash`),
  while `/debate/{id}` links stay readable by anyone who has them; an older database gets the
  column added at startup, and its ownerless rows appear in no list;
- the response cache is gone, so repeating a question uses provider quota again, and the "rerun
  costs nothing" exemption (which reads the database) is gone with it;
- the in-memory per-IP limits start from zero;
- the **global daily cap starts from zero too**, because it is counted from the database. It is a
  guard, not a hard quota: a day with several restarts can exceed 15 debates. The providers' own
  429 responses and the fallback chain are the real backstop.

The Showcase is static files inside the image and is unaffected.

## Option A: test the image locally with the mock config (Docker Desktop)

No keys, no network: every agent is the deterministic mock provider.

1. Install Docker Desktop for Windows (https://www.docker.com/products/docker-desktop/). On
   Windows 11 Home it uses WSL2: accept the WSL2 option in the installer, reboot if asked, start
   Docker Desktop and wait for "Engine running". Check with `docker version`.
2. From the repository root (Git Bash or WSL):

   ```bash
   docker build --build-arg SHOWCASE_STRICT=0 -t tribunal .
   docker images tribunal          # the real image size
   docker run --rm -p 7860:7860 \
     -e AGENTS_CONFIG=/app/backend/config/agents.mock.yaml \
     -e TRUSTED_PROXY=0 \
     tribunal
   ```

   In PowerShell put the `docker run` on one line. In Git Bash, prefix it with `MSYS_NO_PATHCONV=1`
   if the `/app/...` path gets rewritten.
3. Open http://localhost:7860, run a debate, open a showcase example, then reload on
   `/debate/<id>` (the share-link fallback). In another terminal:

   ```bash
   curl -s localhost:7860/api/health
   curl -si localhost:7860/ | head -20       # security headers, no access-control-*
   curl -s localhost:7860/api/agents         # id, role, persona, status, reachable only
   docker exec $(docker ps -q -f ancestor=tribunal) id    # uid=1000(user)
   ```

   The container log should show `rate limiting ON`, `providers with an API key: none` and
   `client-ip check` lines. To see the 429 path, start 6 debates within an hour.

`TRUSTED_PROXY=0` is right for this local test: there is no proxy, and `1` would make the app read
the one-entry header a client can set itself.

## Option B: test as a private Hugging Face Space (build logs only)

1. huggingface.co > New Space > SDK **Docker** > template Blank > hardware CPU basic (free) >
   visibility **Private**.
2. In Settings > Variables and secrets add the **Variables** `AGENTS_CONFIG=config/agents.mock.yaml`
   (relative to `/app/backend`) and `SHOWCASE_STRICT=0`. Add no secrets. Spaces are documented to
   pass Variables to the Docker build as build arguments; if the build still stops on the
   placeholder check, the build log says so and `SHOWCASE_STRICT` was not passed (check the current
   Spaces docs).
3. Prepare a clean copy without git history, eval data or screenshots, prepend the Space front
   matter (below) to its `README.md`, and push that copy to the Space:

   ```bash
   mkdir ../tribunal-space
   git ls-files -co --exclude-standard -z -- . ':!eval' ':!docs/screenshots' ':!.claude' \
     | xargs -0 tar -cf - | tar -xf - -C ../tribunal-space
   cd ../tribunal-space
   # prepend the front matter to README.md here, then:
   git init -b main && git add . && git commit -m "Space test"
   git remote add space https://huggingface.co/spaces/<you>/<space-name>
   git push space main
   ```

   `-co --exclude-standard` takes tracked and untracked files but honours `.gitignore`, so `.env`
   and `*.db` are not copied. Run `ls -a ../tribunal-space` and confirm there is no `.env` before
   pushing anyway.
4. Watch the **Logs** tab: Build (each Dockerfile step), then Container. A good run ends with
   `Uvicorn running on http://0.0.0.0:7860`, a line `rate limiting ON ...` and
   `providers with an API key: none`.

### Space front matter (a deploy step, not part of the GitHub README)

Prepend exactly this to `README.md` in the **Space repository only** (the first line of the file is
`---`):

```yaml
---
title: Tribunal
emoji: ⚖️
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---
```

## Client IP (`TRUSTED_PROXY`): verify after deploying

The per-IP limits use the address that `TRUSTED_PROXY` selects from `X-Forwarded-For`: `N` means
"the Nth entry from the right". How many proxies Hugging Face adds is **not verified**, so `1` is a
starting guess: the smallest value that gives one address per visitor. Wrong in the safe direction
(too low), every visitor shares the proxy's address and the limit becomes a shared one. Wrong in the
unsafe direction (too high), a visitor can choose the address that counts and dodge the per-IP
limit; the global cap and the concurrency cap still apply.

For the first 5 requests (the health check is skipped) the container logs one line each, like this
(illustrative values):

```
"event": "client-ip check", "peer": "10.16.4.0", "xff_entries": 2, "xff": ["203.0.113.0", "10.16.4.0"], "trusted_proxy": 1, "resolved": "10.16.4.0"
```

Addresses are masked: the last IPv4 octet is zeroed and IPv6 is cut to three groups. To check:

1. Open the Space's Logs tab and restart the Space (Settings > Factory reboot) so the counter is
   fresh.
2. Load the app once from your computer, then once from your phone on mobile data (not Wi-Fi).
3. Find each device's public address (search "what is my IP") and compare its first three groups
   with the log lines.
4. **Correct:** `resolved` matches each device's own address, and the two differ.
5. **`resolved` is the same internal-looking address (10.x, 172.16 to 31.x) for both devices:** `N`
   points at a proxy. Find your own address in the `xff` list. If it is the second entry from the
   right, set `TRUSTED_PROXY=2`; if it is somewhere else, send me the log lines.
6. **`xff_entries: 0`:** there is no `X-Forwarded-For`, so `resolved` falls back to the peer and
   everyone shares one limit. Set `TRUSTED_PROXY=0` and rely on the global cap.
7. Change the Space variable, restart, and repeat steps 2 to 4.

The log lines contain no keys, prompts or answers. Uvicorn's access log is off, so addresses and
URLs are not written to the logs otherwise.

## Showcase: replace the placeholders before a public deploy

`frontend/public/showcase/` ships three test-only placeholder files. `npm run build:check` only
warns about them; the Docker build fails on them unless `SHOWCASE_STRICT=0`. To replace them with
real recordings (steps 1 and 2 use your real keys, so you run them):

1. Start the backend on the real config and the frontend (`npm run dev`).
2. Run three real debates that show something distinct (for example a wrong answer losing support,
   a mistake caught, an invalid turn or a fallback).
3. Open `/dev/export/<debateId>` for each (dev server only). It previews the replay with the real
   player and lists sanitiser warnings, such as a provider or model name in free text. Resolve every
   warning by hand: warnings are reported, never rewritten.
4. Download each `<slug>.json` into `frontend/public/showcase/`.
5. Delete the three `placeholder-*.json` files, then run `npm run showcase:index` to rebuild
   `index.json`.
6. From `frontend/`, run `npm run build:check` and then `node scripts/check-bundle.mjs --strict`.
   Both must pass with no `testOnly` warning. The unit tests also check that every shipped file is
   sanitised, listed in the index and free of provider and model names.

## Pre-deploy checklist

Tick every item for the public Space. Commands assume Git Bash at the repository root unless
stated. The image commands need Docker (Option A); for a Space, use its build and container logs
instead.

### Source and history

- [ ] `git status` shows nothing you did not intend to ship, and the deploy comes from a commit, not
      the working tree. Build the bundle with `scripts/make_space_bundle.ps1` (it exports `HEAD`
      only).
- [ ] **No keys in git history.** Search every commit for key shapes (this prints commit ids and
      file names only):

  ```bash
  git log --all --oneline -G'AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-or-[0-9A-Za-z-]{20,}'
  git log --all --diff-filter=A --name-only --format= | grep -Ei '(^|/)\.env' | grep -v '\.env\.example'
  git log --all --name-only --format= | grep -Ei '\.db(-.*)?$'
  ```

  All three must print nothing. Mistral keys have no recognisable prefix, so also search for the
  start of each of your four real keys, in your own terminal and without pasting them anywhere:
  `git log --all --oneline -S'<first 10 characters of the key>'` must print nothing. If anything
  matches, treat that key as leaked and rotate it before doing anything else.
- [ ] `.env` is ignored (`git check-ignore -v .env` names a rule) and not tracked
      (`git ls-files | grep -i '^\.env'` shows only `.env.example`).
- [ ] `.env.example` contains no values (`grep -E 'KEY=.+' .env.example` prints nothing).

### The bundle and the image

- [ ] Review the bundle folder the script printed: list every file, confirm there is no `.env`,
      database, `eval/` or screenshots, and that `README.md` starts with the front matter (the
      commands are in the script's output and in "Option B" above).
- [ ] `.dockerignore` is committed and excludes `.env*`, `.git`, `eval`, `docs`, tests and `*.db`.
- [ ] Image contents (Option A):

  ```bash
  docker run --rm --entrypoint sh tribunal -c 'find /app /home/user -maxdepth 3 -not -path "*/frontend/dist/assets/*" | sort; id'
  docker history --no-trunc tribunal | grep -iE 'key|secret|token' || echo "nothing in history"
  ```

  Expect only `backend/app`, `backend/config`, `frontend/dist`, `data` and `uid=1000(user)`. No
  `.env`, `*.db`, `eval`, tests or `.git`.
- [ ] The public image was built **without** `SHOWCASE_STRICT=0`, and
      `docker run --rm --entrypoint ls tribunal /app/frontend/dist/showcase` lists no
      `placeholder-*` file.

### Behaviour of the running app (the mock config is enough for these)

Start the image as in Option A, run one debate in the browser, and put its id in `ID`.

- [ ] **Reveal data is not served.** All three commands must print `0`:

  ```bash
  ID=<debate id>
  curl -s localhost:7860/api/debates/$ID | grep -Eoi '"(provider|model|label_map)"' | wc -l
  curl -sN --max-time 20 localhost:7860/api/debates/$ID/stream | grep -Eoi '"(provider|model|label_map)"' | wc -l
  curl -s localhost:7860/api/debates | grep -Eoi '"(provider|model|label_map)"' | wc -l
  ```

  Only `GET /api/debates/$ID/reveal` may return them, and it returns `409` while a debate runs.
  `backend/tests/test_reveal.py` also enforces this in CI.
- [ ] `curl -s localhost:7860/api/agents` returns only `id`, `role`, `persona`, `status` and
      `reachable`, and the Space does **not** set `EXPOSE_AGENT_MODELS=true`.
- [ ] **Headers.** `curl -si localhost:7860/` shows a `content-security-policy` (with
      `default-src 'self'`, `object-src 'none'` and the `frame-ancestors` list),
      `x-content-type-options: nosniff` and `referrer-policy: same-origin`, and no
      `x-frame-options` (Hugging Face frames the app).
- [ ] **CORS.** This prints nothing:
      `curl -si -H 'Origin: https://evil.example' localhost:7860/api/health | grep -i access-control`
- [ ] **Static serving.** `curl -so /dev/null -w '%{http_code}\n' localhost:7860/debate/anything`
      prints `200` (the single-page fallback), and the same for `/api/nope` and `/assets/nope.js`
      prints `404`.
- [ ] **Rate limiting.** The first lines of the container log contain `rate limiting ON` and the
      expected numbers, and no Space variable sets `RATE_LIMIT_ENABLED=false`. Starting more
      debates than the hourly limit returns `429`, with a friendly message in the UI.
- [ ] **Banner and notes.** The production page shows the demo banner, the privacy footer and the
      History note (they are compiled out of development builds on purpose).
- [ ] **Logs.** Read the container log of one debate: no prompt text, no answer text and no key
      values (the log scrubber and its tests cover this; confirm it once on the real host).

### The Space itself

- [ ] The four keys are Space **Secrets**, not Variables, and none is blank by accident (the
      startup line `providers with an API key:` lists the ones that are set).
- [ ] The test-only Variables are gone from the public Space: no `AGENTS_CONFIG` pointing at the
      mock config and no `SHOWCASE_STRICT=0`.
- [ ] `TRUSTED_PROXY` was verified from the logs (see "Client IP" above) and its value is set
      deliberately.
- [ ] The Space's `README.md` carries the front matter and the repository's README does not.
- [ ] Visibility: private while testing, public only after every item above is ticked. Remember
      that restarts empty History, the cache and the daily cap (see "What is lost on a restart").
- [ ] One real debate, started by you, finishes; its reveal works; the answer is sensible. Then
      check the provider dashboards for the quota it used.

### Rollback

If something is wrong after going public: set the Space to private (Settings > Change visibility),
which stops visitors at once, then fix and push a new commit. To go back to an earlier version, push
an older bundle to the Space (a force push to the Space repository only, never to GitHub). If a key
may have leaked, rotate it at the provider first, then update the Space Secret.
