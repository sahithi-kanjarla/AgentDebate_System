import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EXAMPLES } from '../lib/examples'
import { resetStoredMemory } from '../lib/safeStorage'
import { getClientId } from '../lib/clientId'
import { stubFetch } from '../test/http'
import { Home } from './Home'

function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/debate/:id" element={<p>debate page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const box = () => screen.getByLabelText('Your question or text') as HTMLTextAreaElement
const start = () => screen.getByRole('button', { name: /start debate|starting/i })

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
  resetStoredMemory()
})

describe('Home', () => {
  it('keeps newlines and indentation in the textarea and sends them unchanged', async () => {
    const fetchMock = stubFetch(() => ({ status: 201, body: { id: 'new1' } }))
    renderHome()
    const code = 'What prints?\n\ndef f():\n    return 1\n'
    fireEvent.change(box(), { target: { value: code } })
    expect(box().value).toBe(code)

    fireEvent.click(start())
    await screen.findByText('debate page')

    const [url, init] = fetchMock.mock.calls.find(([u]) => u === '/api/debates')!
    expect(url).toBe('/api/debates')
    expect(JSON.parse(init!.body as string)).toEqual({ question: code, mode: 'answer' })
    expect((init!.headers as Record<string, string>)['X-Client-Id']).toBe(getClientId())
  })

  it('disables Start for an empty or whitespace-only question', () => {
    renderHome()
    expect(start()).toBeDisabled()
    fireEvent.change(box(), { target: { value: '  \n  ' } })
    expect(start()).toBeDisabled()
    fireEvent.change(box(), { target: { value: 'hello' } })
    expect(start()).toBeEnabled()
  })

  it('counts characters and blocks questions over 4,000', () => {
    renderHome()
    fireEvent.change(box(), { target: { value: 'x'.repeat(4001) } })
    expect(screen.getByText(/4001 \/ 4000/)).toHaveTextContent('too long')
    expect(start()).toBeDisabled()
  })

  it('offers Answer, and Review is disabled with a note', () => {
    renderHome()
    expect(screen.getByRole('radio', { name: /Answer/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Review/ })).toBeDisabled()
    expect(screen.getByText('Coming in a later milestone')).toBeInTheDocument()
  })

  it('fills the textarea from each of the three examples, exactly', () => {
    renderHome()
    expect(EXAMPLES).toHaveLength(3)
    for (const ex of EXAMPLES) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(ex.title) }))
      expect(box().value).toBe(ex.question)
    }
  })

  it('builds the answer format into each example', () => {
    const [code, calculus, opinion] = EXAMPLES
    expect(code!.question).toContain('Give only the printed line.')
    expect(code!.question).toContain('\n    bucket.append(item)')
    expect(calculus!.question).toContain('answer exactly: diverges')
    expect(opinion!.question).toContain('exactly one word: split or keep')
  })

  it('explains a rate limit, says when to retry, links to a recorded debate and keeps the question', async () => {
    const code = 'What prints?\n\ndef f():\n    return 1\n'
    stubFetch((url) =>
      url.includes('showcase/index')
        ? {
            body: {
              format: 1,
              items: [
                {
                  slug: 'demo-one',
                  title: 'Demo one',
                  question: 'q',
                  debaters: 3,
                  rounds: 2,
                  testOnly: false,
                },
              ],
            },
          }
        : {
            status: 429,
            headers: { 'Retry-After': '1380' },
            body: {
              error: 'rate_limited',
              scope: 'ip_hour',
              message: 'You have started the maximum number of debates for this hour.',
              retry_after_s: 1380,
            },
          },
    )
    renderHome()
    fireEvent.change(box(), { target: { value: code } })
    fireEvent.click(start())

    const notice = await screen.findByTestId('rate-limit-notice')
    expect(notice).toHaveTextContent('You have reached the hourly limit')
    expect(notice).toHaveTextContent('Try again in about 23 minutes')
    expect(notice).toHaveTextContent('Your question is still here')
    await waitFor(() =>
      expect(
        within(notice).getByRole('link', { name: 'Watch a recorded debate instead' }),
      ).toHaveAttribute('href', '/showcase/demo-one'),
    )
    expect(box().value).toBe(code)
    await waitFor(() => expect(start()).toBeEnabled())
  })

  it('restores a refused question after a reload, and forgets it once a debate starts', async () => {
    stubFetch((url) =>
      url.includes('showcase')
        ? { status: 404 }
        : {
            status: 429,
            body: { error: 'rate_limited', scope: 'busy', message: 'x', retry_after_s: 30 },
          },
    )
    const first = renderHome()
    fireEvent.change(box(), { target: { value: 'keep me\n  indented' } })
    fireEvent.click(start())
    expect(await screen.findByTestId('rate-limit-notice')).toHaveTextContent('30 seconds')
    first.unmount()

    stubFetch(() => ({ status: 201, body: { id: 'ok1' } }))
    renderHome()
    expect(box().value).toBe('keep me\n  indented')
    fireEvent.click(start())
    await screen.findByText('debate page')
    cleanup()
    renderHome()
    expect(box().value).toBe('')
  })

  it.each([
    ['ip_day', 'You have reached the daily limit'],
    ['global_day', 'Today’s free model quota is used up'],
    ['busy', 'The debaters are busy'],
  ])('has its own wording for the %s limit', async (scope, title) => {
    stubFetch((url) =>
      url.includes('showcase')
        ? { status: 404 }
        : {
            status: 429,
            body: { error: 'rate_limited', scope, message: 'x', retry_after_s: 7200 },
          },
    )
    renderHome()
    fireEvent.change(box(), { target: { value: 'hello' } })
    fireEvent.click(start())
    expect(await screen.findByTestId('rate-limit-notice')).toHaveTextContent(title)
    expect(screen.queryByRole('link', { name: /recorded debate instead/ })).not.toBeInTheDocument()
  })

  it('shows a plain message when the server refuses, and lets the user retry', async () => {
    stubFetch(() => ({ status: 429, body: { detail: 'rate limited' } }))
    renderHome()
    fireEvent.change(box(), { target: { value: 'hello' } })
    fireEvent.click(start())
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many debates started recently')
    await waitFor(() => expect(start()).toBeEnabled())
    expect(box().value).toBe('hello')
  })

  it('says when the backend cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderHome()
    fireEvent.change(box(), { target: { value: 'hello' } })
    fireEvent.click(start())
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server')
  })
})
