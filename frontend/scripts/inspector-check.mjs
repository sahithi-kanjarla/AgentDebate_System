// Dev tool: measures the real layout in Edge. The graph must keep exactly the same size, pan and zoom
// whether nothing, a short or a 20,000-character reasoning is open, and the inspector must be what
// scrolls. Needs `npm run dev`. Usage: node scripts/inspector-check.mjs <outDir> [baseUrl]
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5173'
mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge' })
const failures = []
const check = (ok, msg) => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`)
  if (!ok) failures.push(msg)
}

// Only wide and narrow are kept as pictures. Narrow is a viewport shot: a full-page capture would
// stretch the viewport and show the fixed bottom sheet somewhere it never is.
async function shot(page, name, label) {
  if (label !== 'wide' && label !== 'narrow') return
  await page.screenshot({ path: join(out, `${name}.png`), fullPage: label === 'wide' })
}

async function measure(page) {
  return page.evaluate(() => {
    const r = (el) => {
      const b = el.getBoundingClientRect()
      // y is measured on the page, so scrolling the page does not count as the graph moving
      return [
        Math.round(b.x * 10) / 10,
        Math.round((b.y + window.scrollY) * 10) / 10,
        Math.round(b.width * 10) / 10,
        Math.round(b.height * 10) / 10,
      ]
    }
    const svg = document.querySelector('svg.graph-svg')
    const slot = document.querySelector('[data-testid="inspector-slot"]')
    return {
      stage: r(document.querySelector('.graph-stage')),
      svg: r(svg),
      transform: svg.querySelector(':scope > g:last-of-type').getAttribute('transform'),
      slot: r(slot),
      slotScroll: {
        sh: slot.scrollHeight,
        ch: slot.clientHeight,
        sw: slot.scrollWidth,
        cw: slot.clientWidth,
        top: slot.scrollTop,
      },
      docScrollWidth: document.documentElement.scrollWidth,
      docClientWidth: document.documentElement.clientWidth,
    }
  })
}

for (const [label, viewport] of [
  ['wide', { width: 1280, height: 900 }],
  ['wide-1100', { width: 1100, height: 800 }],
  ['narrow', { width: 390, height: 844 }],
  ['tablet', { width: 900, height: 800 }],
]) {
  const page = await (await browser.newContext({ viewport })).newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(`${base}/dev/graph/longReasoning`)
  await page.waitForSelector('[data-testid="debate-graph"]')
  await page.waitForTimeout(400)
  // pan/zoom by a user gesture first, so we can prove selection does not reset it
  if (label === 'wide') {
    await page.getByRole('button', { name: 'Zoom in' }).click()
    await page.waitForTimeout(300)
  }
  const none = await measure(page)
  const open = async (id) => {
    await page.locator(`[data-node-id="${id}"]`).click({ force: true })
    await page.waitForTimeout(350)
    return measure(page)
  }
  const short = await open('n:0:Debater 2')
  await shot(page, `inspector-short-${label}`, label)
  const long = await open('n:0:Debater 1')
  await shot(page, `inspector-long-${label}`, label)
  const same = (a, b) =>
    JSON.stringify([a.stage, a.svg, a.transform]) === JSON.stringify([b.stage, b.svg, b.transform])
  check(same(none, short), `${label}: graph size, pan and zoom unchanged with a short node open`)
  check(
    same(none, long),
    `${label}: graph size, pan and zoom unchanged with the 20,000-character node open`,
  )
  check(
    long.slotScroll.sh > long.slotScroll.ch,
    `${label}: inspector scrolls itself (scrollHeight ${long.slotScroll.sh} > clientHeight ${long.slotScroll.ch})`,
  )
  check(
    long.slotScroll.sw <= long.slotScroll.cw,
    `${label}: inspector has no horizontal overflow (${long.slotScroll.sw} <= ${long.slotScroll.cw})`,
  )
  check(long.docScrollWidth <= long.docClientWidth, `${label}: page has no horizontal overflow`)
  if (viewport.width >= 1100) {
    check(
      none.slot[2] === 400 && short.slot[2] === 400 && long.slot[2] === 400,
      `${label}: inspector column stays 400px wide`,
    )
    check(none.slot[3] === long.slot[3], `${label}: inspector height fixed (${none.slot[3]} px)`)
    check(
      none.slot[3] > 0 && none.slotScroll.top === 0,
      `${label}: placeholder column is reserved before selection`,
    )
  } else {
    check(
      long.slot[3] <= viewport.height * 0.5 + 2,
      `${label}: bottom sheet at most 50vh (${long.slot[3]} of ${viewport.height})`,
    )
  }
  // scrolling the inspector must not scroll the page
  const before = await page.evaluate(() => window.scrollY)
  await page.locator('[data-testid="inspector-slot"]').hover()
  await page.mouse.wheel(0, 600)
  await page.waitForTimeout(250)
  const after = await measure(page)
  check(
    after.slotScroll.top > 0,
    `${label}: wheel over the inspector scrolls the inspector (top ${after.slotScroll.top})`,
  )
  check((await page.evaluate(() => window.scrollY)) === before, `${label}: ...and not the page`)
  check(same(none, after), `${label}: graph unchanged after scrolling the inspector`)
  await shot(page, `inspector-scrolled-${label}`, label)
  // close with Escape: focus returns to the node, graph still unchanged
  await page.locator('[data-testid="inspector"]').focus()
  await page.keyboard.press('Escape')
  await page.waitForTimeout(250)
  const closed = await measure(page)
  check(same(none, closed), `${label}: graph unchanged after closing`)
  check(
    await page.evaluate(
      () => document.activeElement?.getAttribute('data-node-id') === 'n:0:Debater 1',
    ),
    `${label}: Escape returns focus to the node`,
  )
  check(errors.length === 0, `${label}: no page errors ${errors.join('; ')}`)
  await page.context().close()
}
await browser.close()
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`)
  process.exitCode = 1
} else console.log('\nall layout checks passed')
