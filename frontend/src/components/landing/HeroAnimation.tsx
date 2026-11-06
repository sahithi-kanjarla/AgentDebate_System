import { useEffect, useState } from 'react'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion'

/**
 * A looping picture of one debate, with no question and no real data: a question goes to three
 * debaters, each answers alone, two of them challenge the third, the third changes its answer, and
 * the judge rules. It is an illustration of the process, not a recording. Reduced motion shows the
 * finished picture; otherwise there is a Pause button.
 */
const STEPS = [
  { label: 'Ask', caption: 'You ask a question.' },
  { label: 'Answer alone', caption: 'Each AI answers on its own.' },
  { label: 'Challenge each other', caption: 'They point out each other’s mistakes.' },
  { label: 'Challenge each other', caption: 'One of them changes its answer.' },
  { label: 'Verdict', caption: 'The judge reads everything.' },
  { label: 'Verdict', caption: 'One verdict.' },
] as const
const LAST = STEPS.length - 1
const STEP_MS = 1700
const HOLD_MS = 3400

const DEBATERS = [
  { n: 1, y: 70, color: 'var(--color-debater-1)', tint: 'var(--color-debater-1-tint)' },
  { n: 2, y: 170, color: 'var(--color-debater-2)', tint: 'var(--color-debater-2-tint)' },
  { n: 3, y: 270, color: 'var(--color-debater-3)', tint: 'var(--color-debater-3-tint)' },
] as const

const on = (phase: number, from: number) => (phase >= from ? 'on' : '')

export function HeroAnimation() {
  const reduced = usePrefersReducedMotion()
  const [phase, setPhase] = useState(0)
  const [paused, setPaused] = useState(false)
  const still = reduced

  useEffect(() => {
    if (still || paused) return
    const id = setTimeout(
      () => setPhase((p) => (p >= LAST ? 0 : p + 1)),
      phase >= LAST ? HOLD_MS : STEP_MS,
    )
    return () => clearTimeout(id)
  }, [phase, paused, still])

  const shown = still ? LAST : phase
  const step = STEPS[shown]!
  const stepIndex = ['Ask', 'Answer alone', 'Challenge each other', 'Verdict'].indexOf(step.label)

  return (
    <figure className="hero-art m-0">
      <div>
        <svg
          viewBox="0 0 560 340"
          role="img"
          aria-label="Animation: a question goes to three AI debaters. They answer alone, challenge each other, one changes its answer, and a judge gives one verdict."
          className="mx-auto block h-auto w-full"
        >
          {/* question to each debater */}
          {DEBATERS.map((d) => (
            <path
              key={`q${d.n}`}
              d={`M84,170 C130,170 130,${d.y} 176,${d.y}`}
              fill="none"
              stroke="var(--color-rule-strong)"
              strokeWidth={1.5}
              pathLength={1}
              className={`ha-draw ${on(shown, 1)}`}
            />
          ))}
          <g className="ha-item on">
            <circle cx={60} cy={170} r={24} fill="var(--color-ink)" />
            <text x={60} y={178} textAnchor="middle" className="ha-glyph" fill="var(--color-paper)">
              ?
            </text>
          </g>

          {/* critiques: debaters 1 and 3 challenge debater 2 */}
          <path
            d="M236,84 C320,100 320,140 236,156"
            fill="none"
            stroke="var(--color-ink-soft)"
            strokeWidth={2.5}
            strokeOpacity={0.7}
            pathLength={1}
            className={`ha-draw ${on(shown, 2)}`}
          />
          <path
            d="M236,256 C320,240 320,200 236,184"
            fill="none"
            stroke="var(--color-ink-soft)"
            strokeWidth={2.5}
            strokeOpacity={0.7}
            pathLength={1}
            className={`ha-draw ${on(shown, 2)}`}
          />

          {/* answers to the judge */}
          {DEBATERS.map((d) => (
            <path
              key={`j${d.n}`}
              d={`M300,${d.y} C380,${d.y} 380,170 440,170`}
              fill="none"
              stroke="var(--color-rule-strong)"
              strokeWidth={1.5}
              pathLength={1}
              className={`ha-draw ${on(shown, 4)}`}
            />
          ))}

          {DEBATERS.map((d) => (
            <g key={d.n}>
              <g className="ha-item on">
                <circle
                  cx={200}
                  cy={d.y}
                  r={26}
                  fill={d.tint}
                  stroke={d.color}
                  strokeWidth={2}
                  strokeDasharray={d.n === 2 && shown >= 3 ? '4 3' : undefined}
                />
                <text
                  x={200}
                  y={d.y + 6}
                  textAnchor="middle"
                  className="ha-num"
                  fill="var(--color-ink)"
                >
                  {d.n}
                </text>
                {/* the answer each one holds; debater 2 starts with B and changes to A */}
                {d.n === 2 ? (
                  <>
                    <g className={`ha-swap ${shown >= 1 && shown < 3 ? 'on' : ''}`}>
                      <AnswerChip x={262} y={d.y} letter="B" />
                    </g>
                    <g className={`ha-swap ${shown >= 3 ? 'on' : ''}`}>
                      <AnswerChip x={262} y={d.y} letter="A" />
                    </g>
                  </>
                ) : (
                  <g className={`ha-item ${on(shown, 1)}`}>
                    <AnswerChip x={262} y={d.y} letter="A" />
                  </g>
                )}
              </g>
            </g>
          ))}

          {/* the judge */}
          <g className={`ha-item ${on(shown, 4)}`}>
            <circle cx={470} cy={170} r={30} fill="var(--color-judge)" />
            <text
              x={470}
              y={179}
              textAnchor="middle"
              className="ha-glyph"
              fill="var(--color-paper)"
            >
              J
            </text>
          </g>
          <g className={`ha-item ${on(shown, 5)}`}>
            <rect
              x={436}
              y={88}
              width={68}
              height={32}
              rx={6}
              fill="var(--color-paper)"
              stroke="var(--color-ink)"
              strokeWidth={2}
            />
            <text
              x={470}
              y={109}
              textAnchor="middle"
              className="ha-chip-text"
              fill="var(--color-ink)"
            >
              A
            </text>
            <text
              x={470}
              y={76}
              textAnchor="middle"
              className="ha-label"
              fill="var(--color-ink-soft)"
            >
              Verdict
            </text>
          </g>
        </svg>

        <ol className="mt-4 hidden grid-cols-4 gap-2 sm:grid" aria-label="Steps of a debate">
          {['Ask', 'Answer alone', 'Challenge each other', 'Verdict'].map((label, i) => (
            <li
              key={label}
              aria-current={i === stepIndex ? 'step' : undefined}
              className={`ha-step ${i === stepIndex ? 'is-current' : ''}`}
            >
              <span className="block text-xs text-ink-soft">{i + 1}</span>
              <span className="block text-sm font-medium leading-tight">{label}</span>
            </li>
          ))}
        </ol>
      </div>

      <figcaption className="mt-3 flex items-center justify-between gap-4">
        <span className="text-sm text-ink-soft" aria-live="off">
          {step.caption}
        </span>
        {!reduced && (
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            className="btn btn-secondary btn-sm shrink-0"
            aria-pressed={paused}
          >
            {paused ? 'Play animation' : 'Pause animation'}
          </button>
        )}
      </figcaption>
    </figure>
  )
}

function AnswerChip({ x, y, letter }: { x: number; y: number; letter: string }) {
  return (
    <g>
      <rect
        x={x}
        y={y - 15}
        width={34}
        height={30}
        rx={6}
        fill="var(--color-paper)"
        stroke="var(--color-rule-strong)"
        strokeWidth={1.5}
      />
      <text
        x={x + 17}
        y={y + 5}
        textAnchor="middle"
        className="ha-chip-text"
        fill="var(--color-ink)"
      >
        {letter}
      </text>
    </g>
  )
}
