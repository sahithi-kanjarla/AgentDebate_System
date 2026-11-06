import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Debate } from '../../pages/Debate'
import { parseReveal } from '../../lib/reveal'
import { initialState, reduceAll, streamEnded } from '../../lib/debateState'
import { D1, D2, D3, fullRun } from '../../test/fixtures'
import { FIXTURES } from '../../test/graphFixtures'
import { stubFetch } from '../../test/http'
import { DebateScreen } from '../DebateScreen'

// Invented names: nothing here is a real provider or model, and the page must not show them early.
const MODEL = 'zz-test-model'
const PROVIDER = 'zz-provider'

const slug = (label: string) => label.replace(/\W/g, '')

const entry = (label: string, persona: string) => ({
  label,
  persona,
  primary: { provider: PROVIDER, model: `${MODEL}-${slug(label)}` },
  turns: [0, 1].map((round) => ({
    round,
    provider: PROVIDER,
    model: `${MODEL}-${slug(label)}`,
    fallback_used: false,
    valid: true,
  })),
})

const REVEAL = {
  debate_id: 'd1',
  status: 'completed',
  debaters: [entry(D1, 'Solver'), entry(D2, 'Skeptic'), entry(D3, 'Fact-Checker')],
  judge: entry('Judge', 'Judge'),
  note: 'x',
}

function detail(status: string, events: unknown[] = fullRun()) {
  return {
    id: 'd1',
    question: 'What does this print?',
    mode: 'answer',
    status,
    created_at: '2026-10-18T10:00:00+00:00',
    config: {},
    verdict: null,
    stats: null,
    turns: [],
    events,
  }
}

function renderPage(revealResponse: { status?: number; body?: unknown } = { body: REVEAL }) {
  const fetchMock = stubFetch((url) =>
    url.endsWith('/reveal') ? revealResponse : { body: detail('completed') },
  )
  const view = render(
    <MemoryRouter initialEntries={['/debate/d1']}>
      <Routes>
        <Route path="/debate/:id" element={<Debate />} />
      </Routes>
    </MemoryRouter>,
  )
  return { ...view, fetchMock }
}

const showButton = () => screen.findByRole('button', { name: 'Show which model was which' })

beforeEach(() => window.localStorage.setItem('tribunal.tour.v1', 'done'))
afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('reveal', () => {
  it('is anonymous by default and asks the server only when the button is pressed', async () => {
    const { container, fetchMock } = renderPage()
    await showButton()
    expect(container.textContent).not.toContain(MODEL)
    expect(container.textContent).not.toContain(PROVIDER)
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/reveal'))).toBe(false)
  })

  it('says it is only about who wrote what', async () => {
    renderPage()
    await showButton()
    const panel = screen.getByTestId('reveal-panel')
    expect(panel).toHaveTextContent('This only shows who wrote what')
    expect(panel).toHaveTextContent('not told each other')
  })

  it('shows each debater, and the judge, with their model after the button is pressed', async () => {
    renderPage()
    fireEvent.click(await showButton())
    const rows = await screen.findAllByTestId('revealed-model')
    expect(rows.map((r) => r.textContent)).toEqual([
      `${PROVIDER} / ${MODEL}-Debater1`,
      `${PROVIDER} / ${MODEL}-Debater2`,
      `${PROVIDER} / ${MODEL}-Debater3`,
      `${PROVIDER} / ${MODEL}-Judge`,
    ])
  })

  it('does not change the graph or its answer letters', async () => {
    const { container } = renderPage()
    await showButton()
    const before = container.querySelector('svg.graph-svg')!.outerHTML
    fireEvent.click(screen.getByRole('button', { name: 'Show which model was which' }))
    await screen.findAllByTestId('revealed-model')
    expect(container.querySelector('svg.graph-svg')!.outerHTML).toBe(before)
  })

  it('shows the model in the node inspector, the columns view and the legend', async () => {
    const { container } = renderPage()
    fireEvent.click(await showButton())
    await screen.findAllByTestId('revealed-model')

    fireEvent.click(container.querySelector('[data-node-id="n:1:Debater 2"]')!)
    expect(within(screen.getByTestId('inspector')).getByTestId('model-tag')).toHaveTextContent(
      `${MODEL}-Debater2`,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    fireEvent.click(container.querySelector('[data-node-id="j"]')!)
    expect(within(screen.getByTestId('inspector')).getByTestId('model-tag')).toHaveTextContent(
      `${MODEL}-Judge`,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))

    if (!screen.queryByTestId('legend'))
      fireEvent.click(screen.getByRole('button', { name: 'Legend' }))
    expect(screen.getByTestId('legend-models')).toHaveTextContent(`${MODEL}-Debater3`)

    fireEvent.click(screen.getByRole('button', { name: 'Columns' }))
    expect(screen.getAllByTestId('model-tag').length).toBeGreaterThanOrEqual(3)
  })

  it('marks a turn that a backup answered', async () => {
    const body = structuredClone(REVEAL)
    body.debaters[1]!.turns[1] = {
      round: 1,
      provider: 'zz-backup',
      model: 'zz-backup-model',
      fallback_used: true,
      valid: true,
    }
    const { container } = renderPage({ body })
    fireEvent.click(await showButton())
    await screen.findAllByTestId('revealed-model')
    expect(screen.getByTestId('reveal-panel')).toHaveTextContent(
      'A backup answered round 1 (zz-backup / zz-backup-model)',
    )
    fireEvent.click(container.querySelector('[data-node-id="n:1:Debater 2"]')!)
    const tag = within(screen.getByTestId('inspector')).getByTestId('model-tag')
    expect(tag).toHaveTextContent('zz-backup-model')
    expect(tag).toHaveTextContent('backup')
  })

  it('can be hidden again, and a fresh page view starts anonymous', async () => {
    const first = renderPage()
    fireEvent.click(await showButton())
    await screen.findAllByTestId('revealed-model')
    fireEvent.click(screen.getByRole('button', { name: 'Hide the models' }))
    expect(first.container.textContent).not.toContain(MODEL)
    fireEvent.click(screen.getByRole('button', { name: 'Show which model was which' }))
    await screen.findAllByTestId('revealed-model')
    first.unmount()

    const second = renderPage()
    await showButton()
    expect(second.container.textContent).not.toContain(MODEL)
  })

  it('shows a plain error and keeps the debate anonymous when the server refuses', async () => {
    const { container } = renderPage({ status: 409, body: { detail: 'running' } })
    fireEvent.click(await showButton())
    expect(await screen.findByRole('alert')).toHaveTextContent('still running')
    expect(container.textContent).not.toContain(MODEL)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Show which model/ })).toBeEnabled(),
    )
  })

  it('is not offered while a debate is still running', async () => {
    stubFetch(() => ({ body: detail('running', fullRun().slice(0, 6)) }))
    class Idle {
      addEventListener() {}
      removeEventListener() {}
      close() {}
      onerror = null
    }
    vi.stubGlobal('EventSource', Idle)
    render(
      <MemoryRouter initialEntries={['/debate/d1']}>
        <Routes>
          <Route path="/debate/:id" element={<Debate />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByTestId('question')
    expect(screen.queryByRole('button', { name: /Show which model/ })).not.toBeInTheDocument()
  })
})

describe('recorded examples', () => {
  it('say they are sanitized and offer no reveal', () => {
    const f = FIXTURES.mergeWrongCluster
    const state = streamEnded(reduceAll(f.events, initialState()))
    render(
      <DebateScreen
        header={{
          id: 'slug',
          question: f.question,
          mode: 'answer',
          status: 'completed',
          created_at: '2000-01-01T00:00:00Z',
        }}
        state={state}
        connection="closed"
        events={f.events}
        recorded
      />,
    )
    expect(screen.getByTestId('reveal-sanitized')).toHaveTextContent('sanitized')
    expect(screen.queryByRole('button', { name: /Show which model/ })).not.toBeInTheDocument()
  })
})

describe('parseReveal', () => {
  it('accepts the server shape and refuses anything else', () => {
    expect(parseReveal(REVEAL)?.debaters).toHaveLength(3)
    expect(parseReveal({ debaters: [{ label: 'x' }] })).toBeNull()
    expect(parseReveal(null)).toBeNull()
    expect(parseReveal({ ...REVEAL, judge: { label: 1 } })).toBeNull()
    expect(parseReveal({ ...REVEAL, judge: null })?.judge).toBeNull()
  })
})
