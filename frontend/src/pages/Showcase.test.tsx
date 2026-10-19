import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ShowcaseList } from '../components/ShowcaseList'
import { forbiddenKeyPaths } from '../lib/showcase'
import { stubFetch } from '../test/http'
import { Showcase } from './Showcase'

const read = (name: string): unknown =>
  JSON.parse(readFileSync(join(process.cwd(), 'public', 'showcase', `${name}.json`), 'utf8'))
const SLUG = 'placeholder-wrong-answer-loses'

function mountShowcase(slug = SLUG) {
  return render(
    <MemoryRouter initialEntries={[`/showcase/${slug}`]}>
      <Routes>
        <Route path="/showcase/:slug" element={<Showcase />} />
      </Routes>
    </MemoryRouter>,
  )
}

function stubReducedMotion(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  }))
}

beforeEach(() => {
  window.localStorage.setItem('tribunal.tour.v1', 'done')
  stubReducedMotion(false)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  window.localStorage.clear()
})

describe('Showcase page', () => {
  it('labels the example, flags the placeholder, and starts playing from the beginning', async () => {
    stubFetch((url) => ({ body: read(url.split('/').pop()!.replace('.json', '')) }))
    mountShowcase()
    expect(await screen.findByTestId('recorded-banner')).toHaveTextContent('Recorded example')
    expect(screen.getByTestId('recorded-banner')).toHaveTextContent('No models are being called')
    expect(screen.getByTestId('test-only-chip')).toHaveTextContent('Test-only placeholder')
    // It autoplays from the start: the position is below the end and the button says Pause.
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
    const [pos, total] = screen.getByTestId('replay-status').textContent!.split(' ')[0]!.split('/')
    expect(Number(pos)).toBeLessThan(Number(total))
    expect(screen.queryByRole('heading', { name: 'Verdict' })).toBeNull()
  })

  it('starts at the finished debate, not playing, when the person prefers less motion', async () => {
    stubReducedMotion(true)
    stubFetch((url) => ({ body: read(url.split('/').pop()!.replace('.json', '')) }))
    mountShowcase()
    expect(await screen.findByRole('button', { name: 'Replay' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Verdict' })).toBeInTheDocument()
  })

  it('plays through to the verdict', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    stubFetch((url) => ({ body: read(url.split('/').pop()!.replace('.json', '')) }))
    mountShowcase()
    await screen.findByRole('button', { name: 'Pause' })
    expect(screen.queryByRole('heading', { name: 'Verdict' })).toBeNull()
    // Each tick schedules the next one from an effect, so let React settle between small steps.
    for (let i = 0; i < 400 && !screen.queryByRole('heading', { name: 'Verdict' }); i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500)
      })
    }
    expect(screen.getByRole('heading', { name: 'Verdict' })).toBeInTheDocument()
  })

  it('shows a plain message for a missing or unreadable example', async () => {
    stubFetch(() => ({ status: 404 }))
    mountShowcase('nope')
    expect(await screen.findByRole('alert')).toHaveTextContent('This example does not exist.')
    expect(screen.getByRole('link', { name: 'Back to the start' })).toBeInTheDocument()
  })

  it('refuses a file that carries label_map, provider or model', async () => {
    const dirty = { ...(read(SLUG) as object), label_map: { A: 'x' } }
    stubFetch(() => ({ body: dirty }))
    mountShowcase()
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be read')
  })

  it('never shows label_map, provider or model, even if they are in the data', async () => {
    const file = read(SLUG) as { events: { data: Record<string, unknown> }[] }
    expect(forbiddenKeyPaths(file)).toEqual([])
    stubFetch(() => ({ body: file }))
    mountShowcase()
    await screen.findByTestId('recorded-banner')
    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/label_map|provider|"model"/i)
  })
})

describe('Home: Watch a real debate', () => {
  const renderList = () =>
    render(
      <MemoryRouter>
        <ShowcaseList />
      </MemoryRouter>,
    )

  it('lists the recorded examples with their labels', async () => {
    stubFetch(() => ({ body: read('index') }))
    renderList()
    const section = await screen.findByTestId('showcase-list')
    expect(section).toHaveTextContent('Watch a real debate')
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(3)
    expect(links[0]).toHaveAttribute('href', expect.stringMatching(/^\/showcase\/placeholder-/))
    expect(section.textContent?.match(/Recorded example/g)).toHaveLength(3)
    expect(section.textContent?.match(/Test-only placeholder/g)).toHaveLength(3)
  })

  it('hides itself when the index is missing, broken or empty', async () => {
    stubFetch(() => ({ status: 404 }))
    const a = renderList()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('showcase-list')).toBeNull()
    a.unmount()

    stubFetch(() => ({ body: { format: 7 } }))
    const b = renderList()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('showcase-list')).toBeNull()
    b.unmount()

    stubFetch(() => ({ body: { format: 1, items: [] } }))
    renderList()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('showcase-list')).toBeNull()
  })
})
