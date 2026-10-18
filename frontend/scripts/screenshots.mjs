// Dev tool: screenshots of the Debate Graph fixtures using the installed Microsoft Edge (no browser
// download). Needs `npm run dev` running. Usage: node scripts/screenshots.mjs <outDir> [baseUrl]
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5173'
if (!out) throw new Error('usage: node scripts/screenshots.mjs <outDir> [baseUrl]')
mkdirSync(out, { recursive: true })

const fixtures = ['mergeWrongCluster', 'invalidAndFallback', 'five', 'two', 'seven', 'legacy']
const browser = await chromium.launch({ channel: 'msedge' })
const problems = []

async function open(page, fixture) {
  await page.goto(`${base}/dev/graph/${fixture}`)
  await page.waitForSelector('[data-testid="debate-graph"]')
  await page.waitForTimeout(500)
}

for (const [label, viewport] of [
  ['desktop', { width: 1280, height: 900 }],
  ['mobile', { width: 390, height: 844 }],
]) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: label === 'mobile' ? 2 : 1 })
  const page = await ctx.newPage()
  page.on('console', (m) => m.type() === 'error' && problems.push(`${label}: ${m.text()}`))
  page.on('pageerror', (e) => problems.push(`${label}: ${e.message}`))
  const list = label === 'mobile' ? ['mergeWrongCluster'] : fixtures
  for (const f of list) {
    await open(page, f)
    await page.screenshot({ path: join(out, `graph-${f}-${label}.png`), fullPage: true })
  }
  if (label === 'desktop') {
    await open(page, 'mergeWrongCluster')
    await page.locator('[data-edge-kind="critique"]').nth(1).hover({ force: true })
    await page.waitForTimeout(300)
    await page.screenshot({
      path: join(out, 'graph-mergeWrongCluster-hover-critique.png'),
      fullPage: true,
    })
    await page.mouse.move(5, 5)
    await page.locator('[data-node-id="n:2:Debater 2"]').click()
    await page.waitForTimeout(500)
    await page.screenshot({
      path: join(out, 'graph-mergeWrongCluster-inspector.png'),
      fullPage: true,
    })
  }
  await ctx.close()
}

// live replay: capture mid-run
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()
page.on('pageerror', (e) => problems.push(`live: ${e.message}`))
await page.goto(`${base}/dev/graph/mergeWrongCluster?live=1&ms=350`)
await page.waitForSelector('[data-testid="debate-graph"]')
await page.waitForFunction(() => document.querySelectorAll('.pulse').length > 0, null, {
  timeout: 15000,
})
await page.waitForTimeout(250)
await page.screenshot({ path: join(out, 'graph-mergeWrongCluster-live-pulse.png'), fullPage: true })
await browser.close()

if (problems.length) {
  console.error('browser problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else console.log('screenshots ok')
