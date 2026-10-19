// Rebuilds public/showcase/index.json from the <slug>.json files next to it.
// `node scripts/showcase-index.mjs --check` fails instead of writing when the index is out of date.
// The per-file summary mirrors indexItemFor() in src/lib/showcase.ts.
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = fileURLToPath(new URL('../public/showcase', import.meta.url))
const check = process.argv.includes('--check')
const isRec = (v) => typeof v === 'object' && v !== null && !Array.isArray(v)

function itemFor(file) {
  const started = file.events.find((e) => e.type === 'debate_started')
  const debaters =
    isRec(started?.data) && Array.isArray(started.data.agents) ? started.data.agents.length : 0
  const rounds = new Set()
  let final = null
  for (const e of file.events) {
    if (!isRec(e.data)) continue
    if (e.type === 'agent_response' && typeof e.data.round === 'number') rounds.add(e.data.round)
    if (
      e.type === 'judge_verdict' &&
      isRec(e.data.payload) &&
      typeof e.data.payload.final_answer === 'string'
    ) {
      final = e.data.payload.final_answer
    }
  }
  return {
    slug: file.slug,
    title: file.title,
    question: file.question,
    testOnly: file.testOnly,
    debaters,
    rounds: rounds.size,
    final_answer: final,
  }
}

const items = existsSync(dir)
  ? readdirSync(dir)
      .filter((n) => n.endsWith('.json') && n !== 'index.json')
      .sort()
      .map((n) => JSON.parse(readFileSync(join(dir, n), 'utf8')))
      .map(itemFor)
  : []
const text = JSON.stringify({ format: 1, items }, null, 2) + '\n'
const target = join(dir, 'index.json')

if (check) {
  const current = existsSync(target) ? readFileSync(target, 'utf8') : ''
  if (current !== text) {
    console.error('showcase index.json is out of date; run `npm run showcase:index`')
    process.exit(1)
  }
  console.log(`showcase index ok (${items.length} items)`)
} else {
  writeFileSync(target, text)
  console.log(`wrote ${target} (${items.length} items)`)
}
