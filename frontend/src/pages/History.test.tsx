import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getClientId } from '../lib/clientId'
import { stubFetch } from '../test/http'
import { History } from './History'

const items = [
  {
    id: 'abc',
    question: 'What does this print?\n\nprint(1)',
    mode: 'answer',
    status: 'completed',
    created_at: '2026-10-18T10:00:00+00:00',
    final_answer: '1',
    confidence: 88,
  },
  {
    id: 'def',
    question: 'Is it safe?',
    mode: 'answer',
    status: 'interrupted',
    created_at: '2026-10-18T09:00:00+00:00',
    final_answer: null,
    confidence: null,
  },
]

const renderHistory = () =>
  render(
    <MemoryRouter>
      <History />
    </MemoryRouter>,
  )

afterEach(() => vi.unstubAllGlobals())

describe('History', () => {
  it('lists recent debates, each linking to /debate/{id}', async () => {
    const fetchMock = stubFetch(() => ({ body: items }))
    renderHistory()
    const links = await screen.findAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/debate/abc', '/debate/def'])
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/debates?limit=20')
    const headers = fetchMock.mock.calls[0]![1]?.headers as Record<string, string>
    expect(headers['X-Client-Id']).toMatch(/^[A-Za-z0-9_-]{16,128}$/)
    expect(headers['X-Client-Id']).toBe(getClientId())
  })

  it('shows status, ruling and confidence, and the full question text', async () => {
    stubFetch(() => ({ body: items }))
    renderHistory()
    expect(await screen.findByText('Finished')).toBeInTheDocument()
    expect(screen.getByText('Interrupted')).toBeInTheDocument()
    expect(screen.getByText(/88% confident/)).toBeInTheDocument()
    expect(screen.getByText(/print\(1\)/)).toBeInTheDocument()
  })

  it('invites the user to start one when there are none', async () => {
    stubFetch(() => ({ body: [] }))
    renderHistory()
    expect(await screen.findByText(/No debates yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start the first one' })).toHaveAttribute('href', '/')
  })

  it('reports a load failure', async () => {
    stubFetch(() => ({ status: 500 }))
    renderHistory()
    expect(await screen.findByRole('alert')).toHaveTextContent('The server hit a problem')
  })
})
