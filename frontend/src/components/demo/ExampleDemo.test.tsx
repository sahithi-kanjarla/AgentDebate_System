import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseExamples } from '../../lib/landing'
import { ExampleDemo } from './ExampleDemo'

const set = parseExamples(
  JSON.parse(readFileSync(join(process.cwd(), 'public', 'examples.json'), 'utf8')),
)!

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
afterEach(() => vi.unstubAllGlobals())

describe('ExampleDemo', () => {
  it('offers every real question and starts before anything is sent', () => {
    render(<ExampleDemo set={set} />)
    expect(screen.getAllByRole('radio')).toHaveLength(set.examples.length)
    expect(screen.getByText('You ask a question')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument()
    expect(screen.getByText(/Press Play, or Next stage/)).toBeInTheDocument()
  })

  it('puts Play above the graph', () => {
    render(<ExampleDemo set={set} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next stage' }))
    const play = screen.getByRole('button', { name: /Resume|Play/ })
    const graph = screen.getByRole('group', { name: /Debate graph/i })
    expect(play.compareDocumentPosition(graph) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('opens the question named by initialId', () => {
    const second = set.examples[1]!
    render(<ExampleDemo set={set} initialId={second.id} />)
    expect(screen.getByRole('radio', { checked: true })).toHaveTextContent(second.category)
    expect(screen.getAllByText(second.stem).length).toBeGreaterThan(0)
  })

  it('steps to the verdict and marks the answer key', () => {
    const ex = set.examples[0]!
    render(<ExampleDemo set={set} initialId={ex.id} />)
    const next = screen.getByRole('button', { name: 'Next stage' })
    for (let i = 0; i < ex.rounds.length + 2; i++) fireEvent.click(next)
    expect(screen.getByText(new RegExp(`The judge rules ${ex.final.answer}`))).toBeInTheDocument()
    const options = screen.getByRole('list', { name: 'Answer options' })
    expect(within(options).getByText('Answer key')).toBeInTheDocument()
    expect(next).toBeDisabled()
  })

  it('jumps to a stage from the stage list and goes back', () => {
    render(<ExampleDemo set={set} />)
    const stages = screen.getByRole('list', { name: 'Stages of the debate' })
    fireEvent.click(within(stages).getByRole('button', { name: /Verdict/ }))
    expect(screen.getByText(/The judge rules/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.queryByText(/The judge rules/)).toBeNull()
  })

  it('has exactly the agreed footnote', () => {
    render(<ExampleDemo set={set} />)
    expect(screen.getByText('Real runs from our test set, hand-picked.')).toBeInTheDocument()
  })
})
