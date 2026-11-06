import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseExamples, parsePanel } from '../lib/landing'
import { Landing } from './Landing'

const pub = (name: string): unknown =>
  JSON.parse(readFileSync(join(process.cwd(), 'public', name), 'utf8'))

/** Serves the real public/ files; /api/health answers (or hangs) as asked. */
function stubSite(opts: { healthHangs?: boolean } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) {
        return opts.healthHangs
          ? new Promise<Response>(() => {})
          : Promise.resolve(new Response('{}', { status: 200 }))
      }
      const name = url.replace(/^\/+/, '')
      try {
        return Promise.resolve(new Response(JSON.stringify(pub(name)), { status: 200 }))
      } catch {
        return Promise.resolve(new Response('', { status: 404 }))
      }
    }),
  )
}

function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('prefers-reduced-motion'),
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  }))
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Landing page', () => {
  it('has the headline, the sub-line and two buttons', async () => {
    stubSite()
    renderLanding()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Three AIs argue. One verdict.' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Ask a question. Three AI models answer, challenge each other, and a judge decides. Watch every step.',
      ),
    ).toBeInTheDocument()
    const hero = screen.getByRole('region', { name: 'Three AIs argue. One verdict.' })
    expect(within(hero).getByRole('link', { name: 'Try it' })).toHaveAttribute('href', '/app')
    expect(within(hero).getByRole('link', { name: 'Watch a demo' })).toHaveAttribute(
      'href',
      '/app?tab=demo',
    )
    await screen.findByText('Real runs')
  })

  it('shows the hero animation with no question text', () => {
    stubSite()
    renderLanding()
    const hero = screen.getByRole('region', { name: 'Three AIs argue. One verdict.' })
    expect(within(hero).getByRole('img', { name: /Animation:/ })).toBeInTheDocument()
    expect(within(hero).queryByText(/which of the following|What does this print/i)).toBeNull()
  })

  it('contains no accuracy figures and none of the banned phrases', async () => {
    stubSite()
    const { container } = renderLanding()
    await screen.findByText('Real runs')
    await screen.findByText('Meet the panel')
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/\d+\s*(of|\/)\s*\d+\s*(correct|questions)/i)
    expect(text).not.toMatch(/accuracy|\d\s*%\s*(accurate|correct)/i)
    expect(text).not.toMatch(
      /more accurate|hallucination|production-ready|state-of-the-art|revolutionary|powerful|seamless/i,
    )
    expect(text).toContain('Tested honestly. See the results.')
  })

  it('links the results line to the README Results section in a new tab', async () => {
    stubSite()
    renderLanding()
    const link = await screen.findByRole('link', {
      name: 'See the results.',
    })
    expect(link).toHaveAttribute(
      'href',
      'https://github.com/sahithi-kanjarla/AgentDebate_System#results',
    )
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('offers each real example as a link into the demo', async () => {
    stubSite()
    renderLanding()
    await screen.findByText('Real runs')
    const set = parseExamples(pub('examples.json'))!
    for (const ex of set.examples) {
      const link = screen.getByRole('link', { name: new RegExp(ex.stem.slice(0, 30)) })
      expect(link).toHaveAttribute('href', `/app?tab=demo&q=${ex.id}`)
    }
  })

  it('names the panel from panel.json, without saying which slot is which', async () => {
    stubSite()
    renderLanding()
    await screen.findByText('Meet the panel')
    const panel = parsePanel(pub('panel.json'))!
    for (const d of panel.debaters) {
      expect(screen.getAllByText(d.model).length).toBeGreaterThan(0)
    }
    expect(screen.getAllByTestId('panel-model')).toHaveLength(panel.debaters.length)
    expect(
      screen.getByRole('heading', { name: 'Three models from three labs' }),
    ).toBeInTheDocument()
  })

  it('says the server is waking when the health check is slow', async () => {
    vi.useFakeTimers()
    stubSite({ healthHangs: true })
    renderLanding()
    expect(screen.queryByTestId('waking')).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600)
    })
    expect(screen.getByTestId('waking')).toHaveTextContent('Waking the server')
    expect(
      within(screen.getByTestId('waking')).getByRole('link', { name: 'watch a demo' }),
    ).toHaveAttribute('href', '/app?tab=demo')
  })

  it('does not show the notice when the server answers', async () => {
    stubSite()
    renderLanding()
    await waitFor(() => expect(screen.queryByTestId('waking')).toBeNull())
  })
})

describe('landing data files', () => {
  it('parse, and publish no provider or model names in the examples', () => {
    const set = parseExamples(pub('examples.json'))
    expect(set).not.toBeNull()
    expect(set!.examples.length).toBeGreaterThanOrEqual(3)
    const raw = JSON.stringify(pub('examples.json')).toLowerCase()
    for (const word of ['gemini', 'groq', 'mistral', 'gpt-oss', 'openai', 'provider']) {
      expect(raw).not.toContain(word)
    }
  })

  it('every example is one where debate was right and most debaters started wrong', () => {
    const set = parseExamples(pub('examples.json'))!
    for (const ex of set.examples) {
      const first = ex.rounds[0]!.answers
      const wrong = first.filter((a) => a.answer !== ex.gold).length
      expect(wrong).toBeGreaterThanOrEqual(2)
      expect(ex.final.answer).toBe(ex.gold)
    }
  })
})
