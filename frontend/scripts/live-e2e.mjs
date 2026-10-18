// Dev tool: drives the real UI against a backend running the mock config, through the real SSE
// stream, and saves screenshots. Usage: node scripts/live-e2e.mjs <outDir> [baseUrl]
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5174'
mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge' })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const problems = []
page.on('pageerror', (e) => problems.push(e.message))
page.on('console', (m) => m.type() === 'error' && problems.push(m.text()))

await page.goto(base)
await page.locator('textarea').fill('What does this print?\n\nprint([1, 2, 3])')
await page.getByRole('button', { name: /start debate/i }).click()
await page.waitForURL(/\/debate\//)
await page.waitForSelector('[data-testid="debate-graph"]')
let sawThinking = false
let sawPulse = false
const t0 = Date.now()
while (Date.now() - t0 < 60000) {
  sawThinking ||= (await page.locator('[data-status="thinking"]').count()) > 0
  sawPulse ||= (await page.locator('.pulse').count()) > 0
  if ((await page.locator('[data-status="ruled"]').count()) > 0) break
  await page.waitForTimeout(100)
}
await page.waitForTimeout(800)
await page.screenshot({ path: join(out, 'live-mock-final.png'), fullPage: true })
const info = {
  nodes: await page.locator('[data-node-id]').count(),
  critiques: await page.locator('[data-edge-kind="critique"]').count(),
  sawThinking,
  sawPulse,
  caption: await page.getByTestId('caption').innerText(),
  url: page.url(),
}
// letters: compare what the DOM shows with the raw events the server sent for this debate
const id = page.url().split('/debate/')[1]
const raw = await page.evaluate(
  async (debateId) => (await (await fetch(`/api/debates/${debateId}`)).json()).events,
  id,
)
const answers = {} // round -> agent -> { answer, cluster }
for (const e of raw) {
  if (e.type !== 'agent_response' || e.data.payload.valid === false) continue
  ;(answers[e.data.round] ??= {})[e.data.agent] = {
    answer: e.data.payload.final_answer,
    cluster: e.data.payload.cluster_id,
  }
}
const dom = await page.$$eval('[data-node-id^="n:"]', (els) =>
  els.map((el) => ({ id: el.getAttribute('data-node-id'), label: el.getAttribute('aria-label') })),
)
info.letters = {}
let lettersOk = true
for (const [round, byAgent] of Object.entries(answers)) {
  const shown = {}
  for (const n of dom) {
    const [, r, agent] = n.id.split(':')
    if (r === round) shown[agent] = /Answer ([A-Z])/.exec(n.label)?.[1]
  }
  info.letters[round] = Object.entries(byAgent).map(
    ([a, v]) => `${a}=${shown[a]} (cluster ${v.cluster}, ${JSON.stringify(v.answer)})`,
  )
  for (const a of Object.keys(byAgent))
    for (const b of Object.keys(byAgent)) {
      if ((byAgent[a].answer === byAgent[b].answer) !== (shown[a] === shown[b])) lettersOk = false
    }
}
info.lettersMatchAnswers = lettersOk
if (!lettersOk) process.exitCode = 1

// reload: a finished debate renders from the stored events, with no animation
await page.reload()
await page.waitForSelector('[data-testid="debate-graph"]')
info.reloadedNodes = await page.locator('[data-node-id]').count()
info.reloadedMotion = await page.locator('svg.graph-svg').getAttribute('data-motion')
await page.screenshot({ path: join(out, 'live-mock-reloaded.png'), fullPage: true })
console.log(JSON.stringify(info, null, 2))
if (problems.length) {
  console.error('browser problems:\n' + problems.join('\n'))
  process.exitCode = 1
}
await browser.close()
