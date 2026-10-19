import { line } from 'd3-shape'
import { scaleLinear, scalePoint } from 'd3-scale'
import { confidenceSummary, type ConfidencePoint, type ConfidenceSeries } from '../../lib/insights'
import { STAGE } from '../../lib/palette'
import { ChartFrame } from './ChartFrame'

const W = 300
const H = 64
const M = { l: 12, r: 12, t: 10, b: 10 }
const BRASS = '#c9a24a'

/** One marker shape per debater, so the rows are told apart without colour. */
function Marker({
  index,
  x,
  y,
  hollow,
}: {
  index: number
  x: number
  y: number
  hollow?: boolean
}) {
  const common = {
    fill: hollow ? STAGE.bg : STAGE.ink,
    stroke: STAGE.ink,
    strokeWidth: 1.8,
  }
  const shape = index % 3
  if (shape === 0) return <circle cx={x} cy={y} r={4.5} {...common} />
  if (shape === 1) return <rect x={x - 4.2} y={y - 4.2} width={8.4} height={8.4} {...common} />
  return <path d={`M${x} ${y - 5.5} L${x + 5.2} ${y + 4} L${x - 5.2} ${y + 4} Z`} {...common} />
}

function Cross({ x, y }: { x: number; y: number }) {
  return (
    <path
      d={`M${x - 4} ${y - 4} L${x + 4} ${y + 4} M${x + 4} ${y - 4} L${x - 4} ${y + 4}`}
      stroke={STAGE.inkSoft}
      strokeWidth={2}
      strokeLinecap="round"
    />
  )
}

/** A small multiple per debater on a shared 0 to 100 scale, so rows are comparable. */
export function ConfidenceSparklines({
  series,
  rounds,
}: {
  series: ConfidenceSeries[]
  rounds: number[]
}) {
  const x = scalePoint<number>()
    .domain(rounds)
    .range([M.l, W - M.r])
    .padding(rounds.length > 1 ? 0.3 : 0.5)
  const y = scaleLinear()
    .domain([0, 100])
    .range([H - M.b, M.t])
  const path = line<ConfidencePoint>()
    .defined((p) => p.value !== null)
    .x((p) => x(p.round) ?? 0)
    .y((p) => y(p.value ?? 0))

  const table = {
    caption: 'Confidence each debater reported, in percent',
    head: ['Debater', ...rounds.map((r) => `Round ${r}`)],
    rows: series.map((s) => [
      `${s.label} (${s.persona})`,
      ...s.points.map((p) =>
        p.value !== null ? p.value : p.status === 'invalid' ? 'no valid answer' : 'no answer',
      ),
    ]),
  }

  return (
    <ChartFrame title="Confidence per debater" summary={confidenceSummary(series)} table={table}>
      {({ title, titleId, descId }) =>
        series.length === 0 || rounds.length === 0 ? (
          <p
            className="insights-empty"
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
          >
            <span id={titleId} className="sr-only">
              {title}
            </span>
            Confidence appears once a debater has answered.
          </p>
        ) : (
          <div
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
            data-testid="confidence-chart"
          >
            <span id={titleId} className="sr-only">
              {title}
            </span>
            <ul className="m-0 grid list-none gap-3 p-0">
              {series.map((s) => {
                const known = s.points.filter((p) => p.value !== null)
                const first = known[0]
                const last = known[known.length - 1]
                return (
                  <li
                    key={s.label}
                    className="confidence-row"
                    data-debater={s.label}
                    aria-hidden="true"
                  >
                    <div className="min-w-0">
                      <p className="insights-row-name">{s.label}</p>
                      <p className="insights-row-sub">{s.persona}</p>
                    </div>
                    <svg viewBox={`0 0 ${W} ${H}`} className="insights-spark" focusable="false">
                      <line
                        x1={M.l}
                        x2={W - M.r}
                        y1={y(0)}
                        y2={y(0)}
                        stroke={STAGE.grid}
                        strokeWidth={1}
                      />
                      <line
                        x1={M.l}
                        x2={W - M.r}
                        y1={y(50)}
                        y2={y(50)}
                        stroke={STAGE.grid}
                        strokeWidth={1}
                        strokeDasharray="3 4"
                      />
                      <path
                        d={path(s.points) ?? undefined}
                        fill="none"
                        stroke={STAGE.inkSoft}
                        strokeWidth={2}
                        strokeLinejoin="round"
                      />
                      {s.points.map((p) => {
                        const cx = x(p.round) ?? 0
                        return p.value === null ? (
                          <Cross key={p.round} x={cx} y={y(0) - 8} />
                        ) : (
                          <Marker
                            key={p.round}
                            index={s.index}
                            x={cx}
                            y={y(p.value)}
                            hollow={p !== last}
                          />
                        )
                      })}
                    </svg>
                    <p className="insights-row-value">
                      {first && last && first !== last ? (
                        <>
                          {first.value} <span aria-hidden="true">to</span>{' '}
                          <strong style={{ color: BRASS }}>{last.value}%</strong>
                        </>
                      ) : last ? (
                        <strong style={{ color: BRASS }}>{last.value}%</strong>
                      ) : (
                        <span>no answer</span>
                      )}
                    </p>
                  </li>
                )
              })}
            </ul>
            <p className="insights-note">
              Scale 0 to 100 percent. A cross marks a round with no valid answer.
            </p>
          </div>
        )
      }
    </ChartFrame>
  )
}
