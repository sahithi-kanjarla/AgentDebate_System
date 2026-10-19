import { line } from 'd3-shape'
import { scaleLinear, scalePoint } from 'd3-scale'
import { agreementSummary, type AgreementPoint } from '../../lib/insights'
import { STAGE } from '../../lib/palette'
import { ChartFrame } from './ChartFrame'

const W = 560
const H = 236
const M = { l: 46, r: 30, t: 30, b: 46 }
const BRASS = '#c9a24a'

/**
 * How many debaters agreed after each round. Values are printed on the marks and in a table, so the
 * line is never the only carrier of the data.
 */
export function AgreementChart({ series }: { series: AgreementPoint[] }) {
  const debaters = Math.max(1, ...series.map((p) => p.debaters))
  const x = scalePoint<number>()
    .domain(series.map((p) => p.round))
    .range([M.l, W - M.r])
    .padding(series.length > 1 ? 0.35 : 0.5)
  const y = scaleLinear()
    .domain([0, debaters])
    .range([H - M.b, M.t])
  const path = line<AgreementPoint>()
    .x((p) => x(p.round) ?? 0)
    .y((p) => y(p.agree))(series)

  const ticks = Array.from({ length: debaters + 1 }, (_, i) => i)
  const table = {
    caption: 'Debaters in agreement after each round',
    head: ['Round', 'Agreeing', 'Debaters', 'With a valid answer'],
    rows: series.map((p) => [`Round ${p.round}`, p.agree, p.debaters, p.answered]),
  }

  return (
    <ChartFrame title="Agreement per round" summary={agreementSummary(series)} table={table}>
      {({ title, titleId, descId }) =>
        series.length === 0 ? (
          <p
            className="insights-empty"
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
          >
            <span id={titleId} className="sr-only">
              {title}
            </span>
            Agreement appears once the first round has finished.
          </p>
        ) : (
          <svg
            className="insights-svg"
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
            data-testid="agreement-chart"
          >
            <title id={titleId}>{title}</title>
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={M.l}
                  x2={W - M.r}
                  y1={y(t)}
                  y2={y(t)}
                  stroke={STAGE.grid}
                  strokeWidth={t === debaters ? 1.5 : 1}
                  strokeDasharray={t === debaters ? '5 4' : undefined}
                />
                <text
                  className="gtext gtext-soft"
                  x={M.l - 10}
                  y={y(t) + 4}
                  textAnchor="end"
                  fontSize={12}
                >
                  {t}
                </text>
              </g>
            ))}
            <text
              className="gtext gtext-soft"
              x={M.l + 4}
              y={y(debaters) - 7}
              textAnchor="start"
              fontSize={11}
            >
              everyone agrees
            </text>
            {series.map((p) => (
              <text
                key={p.round}
                className="gtext"
                x={x(p.round)}
                y={H - M.b + 24}
                textAnchor="middle"
                fontSize={13}
              >
                Round {p.round}
              </text>
            ))}
            {path && (
              <path d={path} fill="none" stroke={BRASS} strokeWidth={2.5} strokeLinejoin="round" />
            )}
            {series.map((p) => {
              const cx = x(p.round) ?? 0
              const cy = y(p.agree)
              const full = p.agree === p.debaters
              return (
                <g key={p.round} data-round={p.round}>
                  <circle
                    cx={cx}
                    cy={cy}
                    r={full ? 8 : 6.5}
                    fill={full ? BRASS : STAGE.bg}
                    stroke={BRASS}
                    strokeWidth={2.5}
                  />
                  <text
                    className="gtext"
                    x={cx}
                    y={cy - 15}
                    textAnchor="middle"
                    fontSize={14}
                    fontWeight={600}
                  >
                    {p.agree}/{p.debaters}
                  </text>
                </g>
              )
            })}
          </svg>
        )
      }
    </ChartFrame>
  )
}
