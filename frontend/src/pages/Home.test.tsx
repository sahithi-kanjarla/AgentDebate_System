import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EXAMPLES } from '../lib/examples'
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

afterEach(() => vi.unstubAllGlobals())

describe('Home', () => {
  it('keeps newlines and indentation in the textarea and sends them unchanged', async () => {
    const fetchMock = stubFetch(() => ({ status: 201, body: { id: 'new1' } }))
    renderHome()
    const code = 'What prints?\n\ndef f():\n    return 1\n'
    fireEvent.change(box(), { target: { value: code } })
    expect(box().value).toBe(code)

    fireEvent.click(start())
    await screen.findByText('debate page')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/debates')
    expect(JSON.parse(init!.body as string)).toEqual({ question: code, mode: 'answer' })
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
