import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SourceFactory } from '../hooks/useDebateStream'
import { FakeEventSource } from '../test/fakeEventSource'
import { D2, fullRun } from '../test/fixtures'
import { stubFetch } from '../test/http'
import { Debate } from './Debate'

const factory: SourceFactory = (url) => new FakeEventSource(url) as unknown as EventSource

const QUESTION = 'What does this print?\n\nprint([1, 2, 3])'

function detail(status: string, events: unknown[]) {
  return {
    id: 'd1',
    question: QUESTION,
    mode: 'answer',
    status,
    created_at: '2026-10-18T10:00:00+00:00',
    config: { rounds: 3 },
    verdict: null,
    stats: null,
    // The real endpoint also returns turns that name providers and models.
    turns: [{ provider: 'groq', model: 'secret-model', round: 0 }],
    events,
  }
}

function renderDebate() {
  return render(
    <MemoryRouter initialEntries={['/debate/d1']}>
      <Routes>
        <Route path="/debate/:id" element={<Debate sourceFactory={factory} />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => FakeEventSource.reset())
afterEach(() => vi.unstubAllGlobals())

describe('Debate page: finished debate from a shared URL', () => {
  it('renders the stored events without opening a stream', async () => {
    stubFetch(() => ({ body: detail('completed', fullRun()) }))
    renderDebate()
    expect(await screen.findByRole('heading', { name: 'Verdict' })).toBeInTheDocument()
    expect(FakeEventSource.instances).toHaveLength(0)
    expect(screen.getByText('Round 0: independent answers')).toBeInTheDocument()
    expect(screen.getByText('Round 1: critique and revise')).toBeInTheDocument()
    expect(screen.getByText('2 of 3 agree')).toBeInTheDocument()
    expect(screen.getByText(/All 3 agree/)).toBeInTheDocument()
    expect(screen.getByText('Finished')).toBeInTheDocument()
  })

  it('shows the question exactly as submitted', async () => {
    stubFetch(() => ({ body: detail('completed', fullRun()) }))
    renderDebate()
    await screen.findByRole('heading', { name: 'Verdict' })
    expect(screen.getByTestId('question').textContent).toBe(QUESTION)
  })

  it('shows one column heading per debater with persona badges', async () => {
    stubFetch(() => ({ body: detail('completed', fullRun()) }))
    renderDebate()
    await screen.findByRole('heading', { name: 'Verdict' })
    for (const persona of ['Solver', 'Skeptic', 'Fact-Checker']) {
      expect(screen.getAllByText(persona).length).toBeGreaterThan(0)
    }
  })

  it('explains an interrupted debate and keeps what was captured', async () => {
    const partial = fullRun().slice(0, 8)
    stubFetch(() => ({ body: detail('interrupted', partial) }))
    renderDebate()
    expect(await screen.findByText('No verdict was produced')).toBeInTheDocument()
    expect(
      screen.getByText('This debate was interrupted before the judge ruled.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Round 0: independent answers')).toBeInTheDocument()
  })

  it('says so for an unknown id', async () => {
    stubFetch(() => ({ status: 404, body: { detail: 'debate not found' } }))
    renderDebate()
    expect(await screen.findByRole('heading', { name: 'Debate not found' })).toBeInTheDocument()
  })

  it('shows a load failure', async () => {
    stubFetch(() => ({ status: 500 }))
    renderDebate()
    expect(await screen.findByRole('alert')).toHaveTextContent('The server hit a problem')
  })

  it('never shows provider or model names, or the label map', async () => {
    stubFetch(() => ({ body: detail('completed', fullRun()) }))
    renderDebate()
    await screen.findByRole('heading', { name: 'Verdict' })
    const text = document.body.textContent ?? ''
    for (const word of ['secret-model', 'groq', 'label_map', 'Response 1', 'Response 2']) {
      expect(text).not.toContain(word)
    }
  })
})

describe('Debate page: live debate', () => {
  async function liveWith(events: ReturnType<typeof fullRun>) {
    stubFetch(() => ({ body: detail('running', []) }))
    const view = renderDebate()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.last
    act(() => {
      for (const e of events) es.emit(e.type, e.data, e.seq)
    })
    return { view, es }
  }

  it('follows the stream and closes it after done', async () => {
    const { es } = await liveWith(fullRun())
    expect(await screen.findByRole('heading', { name: 'Verdict' })).toBeInTheDocument()
    expect(es.closed).toBe(true)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('shows a thinking state, then the answer, as events arrive', async () => {
    stubFetch(() => ({ body: detail('running', []) }))
    renderDebate()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const events = fullRun()
    act(() => {
      for (const e of events.slice(0, 4)) FakeEventSource.last.emit(e.type, e.data, e.seq)
    })
    expect(await screen.findAllByText(/is thinking…/)).toHaveLength(3)
    expect(screen.getByText('In progress')).toBeInTheDocument()

    act(() => {
      const answer = events[4]!
      FakeEventSource.last.emit(answer.type, answer.data, answer.seq)
    })
    await waitFor(() => expect(screen.getAllByText(/is thinking…/)).toHaveLength(2))
    expect(screen.getAllByText('[1, 2, 3]').length).toBeGreaterThan(0)
  })

  it('renders exactly the same page as a finished debate with the same events', async () => {
    const { view } = await liveWith(fullRun())
    await screen.findByRole('heading', { name: 'Verdict' })
    const live = view.container.innerHTML
    view.unmount()

    stubFetch(() => ({ body: detail('completed', fullRun()) }))
    const finished = renderDebate()
    await screen.findByRole('heading', { name: 'Verdict' })
    expect(finished.container.innerHTML).toBe(live)
  })

  it('shows an application error without ending the debate', async () => {
    const events = fullRun()
    const { es } = await liveWith(events.slice(0, 6))
    act(() => {
      es.emit('error', { agent: D2, message: 'invalid JSON from agent', recoverable: true }, 99)
    })
    expect(await screen.findByText('1 problem during this debate')).toBeInTheDocument()
    expect(es.closed).toBe(false)
  })

  it('says the debate stopped early if the connection is lost for good', async () => {
    const { es } = await liveWith(fullRun().slice(0, 6))
    act(() => es.connectionError(2))
    expect(await screen.findByText(/stopped before it finished/)).toBeInTheDocument()
    expect(screen.getByText('No verdict was produced')).toBeInTheDocument()
  })
})
