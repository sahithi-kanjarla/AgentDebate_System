import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { reduceAll, type TurnState } from '../lib/debateState'
import type { Severity } from '../lib/types'
import { D1, D2, D3, fullRun } from '../test/fixtures'
import { AnswerChip } from './AnswerChip'
import { ConsensusBand } from './ConsensusBand'
import { RoundCard } from './RoundCard'
import { SeverityMark } from './SeverityMark'
import { VerdictCard } from './VerdictCard'

const state = reduceAll(fullRun())
const turn = (round: number, label: string): TurnState => state.rounds[round]!.turns[label]!

function card(round: number, label: string, index: number, previous?: string) {
  return render(
    <RoundCard
      round={round}
      label={label}
      persona="Skeptic"
      index={index}
      turn={turn(round, label)}
      previousAnswer={previous}
    />,
  )
}

describe('SeverityMark', () => {
  it.each(['low', 'medium', 'high'] as Severity[])(
    'shows a word and a shape for %s, not colour alone',
    (severity) => {
      const { container } = render(<SeverityMark severity={severity} />)
      const word = severity[0]!.toUpperCase() + severity.slice(1)
      expect(screen.getByText(word)).toBeInTheDocument()
      expect(container.querySelector('svg')).not.toBeNull()
    },
  )

  it('uses a different shape for each severity', () => {
    const shapes = (['low', 'medium', 'high'] as Severity[]).map((s) => {
      const { container, unmount } = render(<SeverityMark severity={s} />)
      const html = container.querySelector('svg')!.innerHTML
      unmount()
      return html
    })
    expect(new Set(shapes).size).toBe(3)
  })
})

describe('RoundCard', () => {
  it('shows the changed-mind badge from the server-derived field, with the previous answer', () => {
    card(1, D2, 1, '[1,2,3]')
    expect(screen.getByText('Changed its answer')).toBeInTheDocument()
    expect(screen.getByText('[1,2,3]')).toBeInTheDocument()
  })

  it('shows no changed-mind badge when the server did not derive one', () => {
    card(1, D1, 0)
    expect(screen.queryByText('Changed its answer')).not.toBeInTheDocument()
  })

  it('labels received critiques honestly and never claims a cause', () => {
    const { container } = card(1, D2, 1, '[1,2,3]')
    expect(screen.getByText('Critiques of the answer it revised')).toBeInTheDocument()
    expect(screen.getByText(/From Debater 1/)).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/because|caused|convinced/i)
  })

  it('has no received-critiques section in round 0', () => {
    card(0, D1, 0)
    expect(screen.queryByText('Critiques of the answer it revised')).not.toBeInTheDocument()
    expect(screen.getByText('Independent answer')).toBeInTheDocument()
  })

  it('shows critiques it raised with the resolved target and severity', () => {
    card(1, D1, 0)
    const raised = screen.getByRole('region', { name: 'Critiques it raised' })
    expect(within(raised).getByText('Medium')).toBeInTheDocument()
    expect(raised.textContent).toMatch(/Debater 1\s*→\s*to\s*Debater 2/)
    // The issue text is verbatim, whatever labels it uses.
    expect(within(raised).getByText(/The spacing differs/)).toBeInTheDocument()
  })

  it('collapses reasoning by default', () => {
    const { container } = card(0, D1, 0)
    const details = container.querySelector('details')!
    expect(details.open).toBe(false)
    expect(within(details).getByText('Reasoning')).toBeInTheDocument()
  })

  it('shows a thinking state in words', () => {
    render(
      <RoundCard
        round={0}
        label={D3}
        persona="Fact-Checker"
        index={2}
        turn={{
          status: 'thinking',
          changedMind: false,
          critiques: [],
          receivedCritiques: [],
          fallbackUsed: false,
        }}
        previousAnswer={undefined}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Debater 3 is thinking…')
  })

  it('says who it is waiting for when the round has not reached a debater', () => {
    render(
      <RoundCard
        round={1}
        label={D3}
        persona=""
        index={2}
        turn={undefined}
        previousAnswer={undefined}
      />,
    )
    expect(screen.getByText('Waiting for Debater 3…')).toBeInTheDocument()
  })

  it('explains an invalid turn', () => {
    render(
      <RoundCard
        round={1}
        label={D2}
        persona="Skeptic"
        index={1}
        turn={{
          status: 'invalid',
          error: 'invalid JSON from agent',
          changedMind: false,
          critiques: [],
          receivedCritiques: [],
          fallbackUsed: false,
        }}
        previousAnswer={undefined}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No usable answer this round')
    expect(screen.getByRole('alert')).toHaveTextContent('invalid JSON from agent')
  })

  it('renders the final answer exactly, whitespace included', () => {
    const messy = '  [1,\n    2]\n'
    const { container } = render(
      <RoundCard
        round={0}
        label={D1}
        persona="Solver"
        index={0}
        turn={{ ...turn(0, D1), finalAnswer: messy }}
        previousAnswer={undefined}
      />,
    )
    const answer = container.querySelector('.answer-text')!
    expect(answer.textContent).toBe(messy)
  })
})

describe('ConsensusBand', () => {
  it('says how many agree in words, with segments and grouped answers', () => {
    render(<ConsensusBand round={state.rounds[0]!} />)
    expect(screen.getByText('2 of 3 agree')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '2 of 3 agree' })).toBeInTheDocument()
    expect(screen.getByText('Answer A, held by Debater 1, Debater 3')).toBeInTheDocument()
    expect(screen.getByText('Answer B, held by Debater 2')).toBeInTheDocument()
  })

  it('marks unanimity with words, not just colour', () => {
    render(<ConsensusBand round={state.rounds[1]!} />)
    expect(screen.getByText(/All 3 agree/)).toBeInTheDocument()
  })

  it('gives different answers different patterns', () => {
    const { container } = render(<ConsensusBand round={state.rounds[0]!} />)
    const patterns = [...container.querySelectorAll('.swatch')].map((s) =>
      s.getAttribute('data-pattern'),
    )
    expect(new Set(patterns).size).toBe(2)
  })

  it('renders nothing until the round is complete', () => {
    const open = { ...state.rounds[0]!, summary: null }
    const { container } = render(<ConsensusBand round={open} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('AnswerChip', () => {
  it('shows the answer exactly as received', () => {
    const { container } = render(<AnswerChip clusterId={0} answer={' a\n  b '} />)
    expect(container.querySelector('.answer-text')!.textContent).toBe(' a\n  b ')
  })
})

describe('VerdictCard', () => {
  const verdict = state.verdict!

  it('renders the final answer without trimming or reformatting', () => {
    const messy = '\n  line one\n    line two  \n'
    render(<VerdictCard verdict={{ ...verdict, final_answer: messy }} />)
    const el = screen.getByTestId('final-answer')
    expect(el.textContent).toBe(messy)
    expect(el).toHaveClass('answer-text')
  })

  it('shows confidence as an accessible meter', () => {
    render(<VerdictCard verdict={verdict} />)
    const meter = screen.getByRole('meter', { name: 'Confidence' })
    expect(meter).toHaveAttribute('aria-valuenow', '90')
    expect(screen.getByText('90%')).toBeInTheDocument()
  })

  it('lists mistakes caught with who caught them and when', () => {
    render(<VerdictCard verdict={verdict} />)
    expect(screen.getByRole('heading', { name: 'Mistakes caught (1)' })).toBeInTheDocument()
    expect(screen.getByText('Debater 1 caught this in round 1')).toBeInTheDocument()
    expect(screen.getByText(/The spacing differs/)).toBeInTheDocument()
  })

  it('says so when no mistakes were recorded', () => {
    render(<VerdictCard verdict={{ ...verdict, mistakes_caught: [] }} />)
    expect(screen.getByText('No mistakes were recorded in this debate.')).toBeInTheDocument()
  })

  it('shows dissent only when there is some', () => {
    const { rerender } = render(<VerdictCard verdict={verdict} />)
    expect(screen.queryByRole('heading', { name: 'Dissent' })).not.toBeInTheDocument()
    rerender(
      <VerdictCard verdict={{ ...verdict, dissent: 'Debater 3 preferred another reading.' }} />,
    )
    expect(screen.getByRole('heading', { name: 'Dissent' })).toBeInTheDocument()
    expect(screen.getByText('Debater 3 preferred another reading.')).toBeInTheDocument()
  })

  it('states whether consensus was reached', () => {
    const { rerender } = render(<VerdictCard verdict={verdict} />)
    expect(screen.getByText('The debaters reached consensus')).toBeInTheDocument()
    rerender(<VerdictCard verdict={{ ...verdict, consensus_reached: false }} />)
    expect(screen.getByText('The debaters did not reach consensus')).toBeInTheDocument()
  })
})
