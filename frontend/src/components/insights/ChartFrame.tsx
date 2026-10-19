import { useId, useState, type ReactNode } from 'react'

export interface TableData {
  caption: string
  head: string[]
  rows: (string | number)[][]
}

interface Props {
  /** Short name of the chart, used as its accessible name. */
  title: string
  /** One sentence that says what the chart shows; read aloud and printed under the chart. */
  summary: string
  table: TableData
  /** The drawing. It gets the name and ids to wire up as `role="img"` with a title and description. */
  children: (a11y: { title: string; titleId: string; descId: string }) => ReactNode
}

/**
 * Every chart gets the same text alternatives: an accessible name, a one-sentence summary printed
 * under it, and a real data table. The table is always in the document (so screen readers can reach
 * it); "Show as table" only reveals it for sighted readers.
 */
export function ChartFrame({ title, summary, table, children }: Props) {
  const uid = useId()
  const titleId = `${uid}-title`
  const descId = `${uid}-desc`
  const [open, setOpen] = useState(false)

  return (
    <figure className="m-0">
      {children({ title, titleId, descId })}
      <figcaption className="mt-2 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <p
          id={descId}
          className="insights-summary max-w-[68ch] text-sm"
          data-testid="chart-summary"
        >
          {summary}
        </p>
        <button
          type="button"
          className="insights-btn"
          aria-pressed={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Hide table' : 'Show as table'}
        </button>
      </figcaption>
      <div className={open ? 'insights-table-wrap' : 'sr-only'} data-testid="chart-table">
        <table className="insights-table">
          <caption>{table.caption}</caption>
          <thead>
            <tr>
              {table.head.map((h, i) => (
                <th key={i} scope="col">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) =>
                  c === 0 ? (
                    <th key={c} scope="row">
                      {cell}
                    </th>
                  ) : (
                    <td key={c}>{cell}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
