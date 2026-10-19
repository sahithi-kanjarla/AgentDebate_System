// Dev tool: screenshots and layout checks of the M5a screens (replay bar, graph, Insights, linked
// verdict, tour, Showcase, Home) at 360, 768 and desktop widths, using the installed Microsoft Edge
// (no browser download). TEST-ONLY fixtures and the placeholder showcase files only; no backend, no
// keys. Needs `npm run dev` running. Usage: node scripts/screenshots-m5a.mjs <outDir> [baseUrl]
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5173'
if (!out) throw new Error('usage: node scripts/screenshots-m5a.mjs <outDir> [baseUrl]')
mkdirSync(out, { recursive: true })

const SHOWCASE = 'placeholder-wrong-answer-loses'
const TOUR_KEY = 'tribunal.tour.v1'

const browser = await chromium.launch({ channel: 'msedge' })
const problems = []
const facts = []
const fact = (s) => facts.push(s)
const problem = (s) => problems.push(s)

function watch(page, label) {
  page.on('console', (m) => m.type() === 'error' && problem(`${label}: console error: ${m.text()}`))
  page.on('pageerror', (e) => problem(`${label}: ${e.message}`))
}

async function context(kind, { tourSeen = true, reducedMotion = 'no-preference' } = {}) {
  const opts = {
    phone: {
      viewport: { width: 360, height: 780 },
      deviceScaleFactor: 2,
      hasTouch: true,
      isMobile: true,
    },
    tablet: { viewport: { width: 768, height: 1024 }, deviceScaleFactor: 1, hasTouch: true },
    desktop: { viewport: { width: 1280, height: 900 } },
  }[kind]
  const ctx = await browser.newContext({ ...opts, reducedMotion })
  if (tourSeen) await ctx.addInitScript((k) => localStorage.setItem(k, 'done'), TOUR_KEY)
  return ctx
}

async function openDebate(page, fixture) {
  await page.goto(`${base}/dev/debate/${fixture}`)
  await page.waitForSelector('[data-testid="debate-graph"]')
  await page.waitForSelector('[data-testid="insights"]')
  await page.waitForTimeout(500)
}

async function overflow(page, label) {
  const o = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    iw: window.innerWidth,
  }))
  fact(`${label}: page scrollWidth ${o.sw} / innerWidth ${o.iw}`)
  if (o.sw > o.iw) problem(`${label}: horizontal page scroll`)
}

const box = (page, sel) =>
  page.evaluate((s) => {
    const el = document.querySelector(s)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { x: r.x, y: r.y, w: r.width, h: r.height, r: r.right, b: r.bottom }
  }, sel)

/** Every answer node, fully inside the graph's visible area? */
async function graphFits(page, label) {
  const r = await page.evaluate(() => {
    const svg = document.querySelector('.graph-svg').getBoundingClientRect()
    const nodes = [...document.querySelectorAll('.graph-svg [data-node-kind]')].map((n) =>
      n.getBoundingClientRect(),
    )
    const out = nodes.filter(
      (n) => (n.left + n.right) / 2 < svg.left || (n.left + n.right) / 2 > svg.right,
    )
    return { total: nodes.length, outside: out.length, svgW: Math.round(svg.width) }
  })
  fact(
    `${label}: ${r.total - r.outside}/${r.total} graph nodes inside the ${r.svgW}px stage on first load`,
  )
  if (r.outside > 0) problem(`${label}: ${r.outside} nodes are outside the stage on first load`)
}

async function tab(page, name) {
  await page.getByRole('tab', { name }).click()
  await page.waitForTimeout(150)
}

// ---------- desktop
{
  const ctx = await context('desktop')
  const d = await ctx.newPage()
  watch(d, 'desktop')
  for (const f of ['mergeWrongCluster', 'invalidAndFallback', 'five']) {
    await openDebate(d, f)
    await overflow(d, `desktop ${f}`)
    await graphFits(d, `desktop ${f}`)
    await d.screenshot({ path: join(out, `m5a-${f}-desktop.png`), fullPage: true })
  }
  await openDebate(d, 'mergeWrongCluster')
  for (const [name, file] of [
    ['Agreement', 'agreement'],
    ['Answer flow', 'flow'],
    ['Confidence', 'confidence'],
  ]) {
    await tab(d, name)
    await d.getByTestId('insights').screenshot({ path: join(out, `m5a-insights-${file}.png`) })
  }
  await openDebate(d, 'mergeWrongCluster')
  await d.getByRole('button', { name: /^Replay$/ }).click()
  await d.waitForTimeout(4500)
  await d.screenshot({ path: join(out, 'm5a-replay-mid-playback.png') })

  await openDebate(d, 'mergeWrongCluster')
  await d.getByTestId('mistake-item').first().hover()
  await d.waitForTimeout(250)
  await d.locator('[data-testid="mistake-item"]').first().scrollIntoViewIfNeeded()
  await d.screenshot({ path: join(out, 'm5a-linked-verdict.png'), fullPage: true })

  // Home with the Showcase section, and the Showcase page mid-play.
  await d.goto(`${base}/`)
  await d.waitForSelector('[data-testid="showcase-list"]')
  await overflow(d, 'desktop home')
  await d.screenshot({ path: join(out, 'm5a-home-showcase.png'), fullPage: true })
  await d.getByRole('link', { name: /a wrong answer loses support/ }).click()
  await d.waitForSelector('[data-testid="recorded-banner"]')
  await d.waitForTimeout(4000)
  await overflow(d, 'desktop showcase')
  await d.screenshot({ path: join(out, 'm5a-showcase-desktop.png') })
  await ctx.close()
}

// ---------- tour (fresh storage, so it opens by itself)
{
  const ctx = await context('desktop', { tourSeen: false })
  const d = await ctx.newPage()
  watch(d, 'tour')
  await d.goto(`${base}/dev/debate/mergeWrongCluster`)
  await d.waitForSelector('[data-testid="tour"]')
  await d.waitForTimeout(700)
  const titles = []
  for (let i = 1; i <= 5; i++) {
    await d.waitForTimeout(700)
    titles.push(await d.locator('.tour-title').innerText())
    await d.screenshot({ path: join(out, `m5a-tour-${i}.png`) })
    if (i < 5) await d.locator('.tour-next').click()
  }
  fact(`tour steps: ${titles.join(' | ')}`)
  const focusInDialog = await d.evaluate(() =>
    document.querySelector('[data-testid="tour"]').contains(document.activeElement),
  )
  fact(`tour focus inside dialog: ${focusInDialog}`)
  await d.keyboard.press('Escape')
  await d.waitForTimeout(200)
  const gone = (await d.locator('[data-testid="tour"]').count()) === 0
  fact(`tour closes on Escape: ${gone}`)
  if (!gone) problem('tour did not close on Escape')
  await d.reload()
  await d.waitForSelector('[data-testid="debate-graph"]')
  await d.waitForTimeout(500)
  const back = (await d.locator('[data-testid="tour"]').count()) > 0
  fact(`tour stays away after skip + reload: ${!back}`)
  if (back) problem('tour came back after being skipped')
  await ctx.close()
}

// ---------- phone
{
  const ctx = await context('phone')
  const p = await ctx.newPage()
  watch(p, '360')
  for (const f of ['mergeWrongCluster', 'five', 'seven']) {
    await openDebate(p, f)
    await overflow(p, `360 ${f}`)
    await graphFits(p, `360 ${f}`)
  }
  await openDebate(p, 'mergeWrongCluster')
  await p.screenshot({ path: join(out, 'm5a-mergeWrongCluster-360.png'), fullPage: true })

  const bar = await box(p, '[data-testid="replay-bar"]')
  fact(`360: replay bar ${Math.round(bar.h)}px tall (was 153)`)
  if (bar.h > 125) problem(`360: replay bar is ${Math.round(bar.h)}px tall`)
  const small = await p.evaluate(() =>
    [
      ...document.querySelectorAll(
        '[data-testid="replay-bar"] button, [data-testid="replay-bar"] input',
      ),
    ]
      .filter((e) => e.offsetParent !== null)
      .map((e) => ({
        n: e.getAttribute('aria-label') || e.textContent.trim(),
        h: Math.round(e.getBoundingClientRect().height),
        w: Math.round(e.getBoundingClientRect().width),
      }))
      .filter((e) => e.h < 36 || e.w < 36),
  )
  fact(`360: replay targets under 36px: ${JSON.stringify(small)}`)
  if (small.length) problem(`360: small replay targets ${JSON.stringify(small)}`)
  const overlap = await p.evaluate(() => {
    const items = [
      ...document.querySelectorAll(
        '[data-testid="replay-bar"] button, [data-testid="replay-bar"] input',
      ),
    ]
      .filter((e) => e.offsetParent !== null)
      .map((e) => e.getBoundingClientRect())
    const barR = document.querySelector('[data-testid="replay-bar"]').getBoundingClientRect()
    let n = 0
    for (let i = 0; i < items.length; i++) {
      if (items[i].left < barR.left - 1 || items[i].right > barR.right + 1) n++
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i],
          c = items[j]
        if (
          Math.min(a.right, c.right) - Math.max(a.left, c.left) > 1 &&
          Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top) > 1
        )
          n++
      }
    }
    return n
  })
  fact(`360: replay overlaps/clipped: ${overlap}`)
  if (overlap) problem('360: replay controls overlap or are clipped')
  await p.getByRole('button', { name: /^Speed/ }).click()
  await p.waitForTimeout(150)
  await p
    .locator('[data-testid="replay-bar"]')
    .screenshot({ path: join(out, 'm5a-replay-bar-360-speeds.png') })
  await p.getByRole('button', { name: /^Speed/ }).click()
  await p
    .locator('[data-testid="replay-bar"]')
    .screenshot({ path: join(out, 'm5a-replay-bar-360.png') })

  const tabs = await p.evaluate(() => {
    const list = document.querySelector('.insights-tabs')
    const l = list.getBoundingClientRect()
    return {
      scroll: list.scrollWidth,
      client: list.clientWidth,
      clipped: [...list.querySelectorAll('[role=tab]')].filter(
        (t) =>
          t.getBoundingClientRect().right > l.right + 1 ||
          t.getBoundingClientRect().left < l.left - 1,
      ).length,
    }
  })
  fact(
    `360: insights tabs scrollWidth/clientWidth ${tabs.scroll}/${tabs.client}, clipped tabs ${tabs.clipped}`,
  )
  if (tabs.clipped || tabs.scroll > tabs.client) problem('360: insights tabs are clipped')

  for (const [name, file] of [
    ['Agreement', 'agreement'],
    ['Answer flow', 'flow'],
    ['Confidence', 'confidence'],
  ]) {
    await tab(p, name)
    await overflow(p, `360 ${name}`)
    await p.getByTestId('insights').screenshot({ path: join(out, `m5a-${file}-360.png`) })
  }

  // Fit button: pan with the keyboard, then Fit brings the whole graph back.
  await p.locator('.graph-svg').focus()
  const tf = () =>
    p.evaluate(() =>
      document
        .querySelector('.graph-svg > g:last-of-type, .graph-svg g[transform]')
        ?.getAttribute('transform'),
    )
  const before = await tf()
  for (let i = 0; i < 6; i++) await p.keyboard.press('ArrowLeft')
  await p.waitForTimeout(100)
  const panned = await tf()
  await p.getByRole('button', { name: 'Fit', exact: true }).click()
  await p.waitForTimeout(150)
  const after = await tf()
  fact(`360: graph transform first ${before} | panned ${panned} | after Fit ${after}`)
  if (panned === before) problem('360: keyboard pan did not move the graph')
  if (after !== before) problem('360: Fit did not restore the fitted view')

  // The inspector bottom sheet must not resize the graph.
  const g0 = await box(p, '.graph-svg')
  await p.locator('[data-node-kind="answer"]').first().click({ force: true })
  await p.waitForTimeout(500)
  const g1 = await box(p, '.graph-svg')
  fact(
    `360: graph box with sheet closed ${Math.round(g0.w)}x${Math.round(g0.h)} / open ${Math.round(g1.w)}x${Math.round(g1.h)}`,
  )
  if (Math.abs(g0.h - g1.h) > 1 || Math.abs(g0.w - g1.w) > 1)
    problem('360: inspector sheet resized the graph')
  await p.screenshot({ path: join(out, 'm5a-inspector-sheet-360.png') })
  await ctx.close()
}

// ---------- phone: tour, showcase, home
{
  const ctx = await context('phone', { tourSeen: false })
  const p = await ctx.newPage()
  watch(p, '360 tour')
  await p.goto(`${base}/dev/debate/mergeWrongCluster`)
  await p.waitForSelector('[data-testid="tour"]')
  await p.waitForTimeout(700)
  await p.screenshot({ path: join(out, 'm5a-tour-360.png') })
  const card = await box(p, '[data-testid="tour"]')
  fact(`360: tour card ${Math.round(card.h)}px tall, bottom ${Math.round(card.b)} of 780`)
  await overflow(p, '360 with tour')
  await ctx.close()

  const ctx2 = await context('phone')
  const q = await ctx2.newPage()
  watch(q, '360 home')
  await q.goto(`${base}/`)
  await q.waitForSelector('[data-testid="showcase-list"]')
  await overflow(q, '360 home')
  await q.screenshot({ path: join(out, 'm5a-home-360.png'), fullPage: true })
  await q.goto(`${base}/showcase/${SHOWCASE}`)
  await q.waitForSelector('[data-testid="recorded-banner"]')
  await q.waitForTimeout(3000)
  await overflow(q, '360 showcase')
  await q.screenshot({ path: join(out, 'm5a-showcase-360.png') })
  await ctx2.close()
}

// ---------- tablet
{
  const ctx = await context('tablet')
  const t = await ctx.newPage()
  watch(t, '768')
  await openDebate(t, 'mergeWrongCluster')
  await overflow(t, '768 mergeWrongCluster')
  await graphFits(t, '768 mergeWrongCluster')
  await t.screenshot({ path: join(out, 'm5a-mergeWrongCluster-768.png'), fullPage: true })
  const g0 = await box(t, '.graph-svg')
  await t.locator('[data-node-kind="answer"]').first().click({ force: true })
  await t.waitForTimeout(500)
  const g1 = await box(t, '.graph-svg')
  fact(
    `768: graph box closed ${Math.round(g0.w)}x${Math.round(g0.h)} / open ${Math.round(g1.w)}x${Math.round(g1.h)}`,
  )
  if (Math.abs(g0.h - g1.h) > 1 || Math.abs(g0.w - g1.w) > 1)
    problem('768: inspector resized the graph')
  await ctx.close()
}

// ---------- reduced motion
{
  const ctx = await context('desktop', { reducedMotion: 'reduce' })
  const r = await ctx.newPage()
  watch(r, 'reduced')
  await r.goto(`${base}/showcase/${SHOWCASE}`)
  await r.waitForSelector('[data-testid="recorded-banner"]')
  await r.waitForTimeout(800)
  const status = await r.getByTestId('replay-status').innerText()
  const verdict = await r.getByRole('heading', { name: 'Verdict' }).count()
  fact(
    `reduced motion: showcase opens at "${status.split(' ').slice(0, 1)}" with verdict visible: ${verdict > 0}`,
  )
  if (!verdict) problem('reduced motion: showcase did not open on the finished debate')
  await ctx.close()
}

await browser.close()
console.log(facts.join('\n'))
if (problems.length) {
  console.error('PROBLEMS:\n' + problems.join('\n'))
  process.exitCode = 1
} else console.log('\nno console errors, no layout problems')
