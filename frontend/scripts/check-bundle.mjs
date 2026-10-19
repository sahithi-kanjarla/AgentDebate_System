// Fails if the production bundle contains test fixtures or the dev-only graph route.
// `--strict` (the Docker build and the deploy checklist) also fails while any test-only
// placeholder showcase file ships; without it that is only a warning, so CI stays green.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const FORBIDDEN = [
  'TEST-ONLY',
  'mergeWrongCluster',
  'invalidAndFallback',
  'fixture-merge',
  'fixture-seven',
  '/dev/graph',
  'DevGraph',
  '/dev/debate',
  'DevDebate',
  '/dev/export',
  'DevExport',
]

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* files(path)
    else yield path
  }
}

const dist = fileURLToPath(new URL('../dist', import.meta.url))
const hits = []
let scanned = 0
for (const file of files(dist)) {
  if (!/\.(js|css|html|map)$/.test(file)) continue
  scanned++
  const text = readFileSync(file, 'utf8')
  for (const needle of FORBIDDEN) if (text.includes(needle)) hits.push(`${file}: ${needle}`)
}
if (scanned === 0) {
  console.error('check-bundle: no built files found; run `npm run build` first.')
  process.exit(2)
}
if (hits.length > 0) {
  console.error(
    'check-bundle: test-only code leaked into the production bundle:\n' + hits.join('\n'),
  )
  process.exit(1)
}
// Placeholder showcase files are .json, so the scan above skips them. List any that still ship so they
// are replaced with real recordings (or deleted) before a deployment.
const showcase = join(dist, 'showcase')
const placeholders = existsSync(showcase)
  ? readdirSync(showcase).filter((n) => {
      if (!n.endsWith('.json') || n === 'index.json') return false
      try {
        return JSON.parse(readFileSync(join(showcase, n), 'utf8')).testOnly === true
      } catch {
        return false
      }
    })
  : []
if (placeholders.length > 0) {
  const strict = process.argv.includes('--strict')
  const message = `${placeholders.length} test-only showcase file(s) still ship: ${placeholders.join(', ')}. Replace them with real recordings before deploying.`
  if (strict) {
    console.error(`check-bundle: ${message}`)
    process.exit(1)
  }
  console.warn(`check-bundle: WARNING ${message}`)
}
console.log(`check-bundle: ok (${scanned} files scanned, no fixtures or /dev/graph route)`)
