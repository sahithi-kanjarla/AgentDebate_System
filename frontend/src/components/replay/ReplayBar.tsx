import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { Replay } from '../../hooks/useReplay'
import { SPEEDS, type Speed } from '../../lib/replay'

/** A spoken status only after the position stops changing, and never while the replay plays. */
const SETTLE_MS = 400

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

const PrevRound = () => (
  <Icon>
    <path d="M3 3h2v12H3zM16 3v12L7 9z" />
  </Icon>
)
const StepBack = () => (
  <Icon>
    <path d="M12.5 3v12L5 9z" />
  </Icon>
)
const StepFwd = () => (
  <Icon>
    <path d="M5.5 3v12L13 9z" />
  </Icon>
)
const NextRound = () => (
  <Icon>
    <path d="M13 3h2v12h-2zM2 3v12l9-6z" />
  </Icon>
)
const PlayIcon = () => (
  <Icon>
    <path d="M5 2.5v13L15.5 9z" />
  </Icon>
)
const PauseIcon = () => (
  <Icon>
    <path d="M4.5 3h3.5v12H4.5zM10 3h3.5v12H10z" />
  </Icon>
)
const ReplayIcon = () => (
  <Icon>
    <path d="M9 3a6 6 0 1 0 5.7 7.9h-2.1A4 4 0 1 1 9 5v2.6L13.6 4 9 .4z" />
  </Icon>
)

function SpeedGroup({
  speed,
  onChange,
  id,
  open,
}: {
  speed: Speed
  onChange: (s: Speed) => void
  id: string
  open: boolean
}) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = SPEEDS.indexOf(speed)
    let next = i
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = Math.min(SPEEDS.length - 1, i + 1)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = Math.max(0, i - 1)
    else return
    e.preventDefault()
    onChange(SPEEDS[next]!)
    const group = e.currentTarget.parentElement
    requestAnimationFrame(() =>
      group?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus(),
    )
  }
  return (
    <div
      role="radiogroup"
      aria-label="Playback speed"
      className="replay-speeds"
      id={id}
      data-open={open ? '' : undefined}
    >
      {SPEEDS.map((s) => (
        <button
          key={s}
          type="button"
          role="radio"
          aria-checked={speed === s}
          tabIndex={speed === s ? 0 : -1}
          className="replay-speed"
          onClick={() => onChange(s)}
          onKeyDown={onKey}
        >
          {s}×
        </button>
      ))}
    </div>
  )
}

/**
 * Transport controls for a finished debate. It only drives `useReplay`; the page, the graph, the
 * narrator, the charts and the verdict all read the position from there.
 */
export function ReplayBar({ replay }: { replay: Replay }) {
  const { position, total, playing } = replay
  const atEnd = position >= total
  const atStart = position <= 0

  const [spoken, setSpoken] = useState('')
  useEffect(() => {
    if (playing || !replay.touched) {
      setSpoken('')
      return
    }
    const id = setTimeout(() => setSpoken(replay.valueText), SETTLE_MS)
    return () => clearTimeout(id)
  }, [playing, replay.touched, replay.valueText])

  // On a phone the four speeds sit behind one button; on wider screens CSS shows them inline.
  const uid = useId()
  const [speedOpen, setSpeedOpen] = useState(false)

  const playLabel = playing ? 'Pause' : atEnd ? 'Replay' : 'Play'

  return (
    <section className="replay-bar" aria-label="Replay" data-testid="replay-bar">
      <div className="replay-controls">
        <button
          type="button"
          className="replay-btn"
          aria-label="Previous round"
          title="Previous round"
          onClick={() => replay.jumpRound(-1)}
          aria-disabled={atStart}
        >
          <PrevRound />
        </button>
        <button
          type="button"
          className="replay-btn"
          aria-label="Previous event"
          title="Previous event"
          onClick={() => replay.step(-1)}
          aria-disabled={atStart}
        >
          <StepBack />
        </button>
        <button
          type="button"
          className="replay-play"
          aria-pressed={playing}
          onClick={replay.toggle}
        >
          {playing ? <PauseIcon /> : atEnd ? <ReplayIcon /> : <PlayIcon />}
          <span>{playLabel}</span>
        </button>
        <button
          type="button"
          className="replay-btn"
          aria-label="Next event"
          title="Next event"
          onClick={() => replay.step(1)}
          aria-disabled={atEnd}
        >
          <StepFwd />
        </button>
        <button
          type="button"
          className="replay-btn"
          aria-label="Next round"
          title="Next round"
          onClick={() => replay.jumpRound(1)}
          aria-disabled={atEnd}
        >
          <NextRound />
        </button>
      </div>

      <div className="replay-scrubber">
        <input
          type="range"
          className="replay-range"
          aria-label="Replay position"
          min={0}
          max={total}
          step={1}
          value={position}
          aria-valuetext={replay.valueText}
          onChange={(e) => replay.seek(Number(e.currentTarget.value))}
          style={{ ['--fill' as string]: `${total === 0 ? 0 : (position / total) * 100}%` }}
        />
        <p className="replay-status" data-testid="replay-status">
          <span className="replay-count">
            {position}/{total}
          </span>{' '}
          {atEnd ? 'The finished debate' : replay.valueText.replace(/^Event \d+ of \d+: /, '')}
        </p>
      </div>

      <button
        type="button"
        className="replay-speed-toggle"
        aria-expanded={speedOpen}
        aria-controls={`${uid}-speeds`}
        onClick={() => setSpeedOpen((v) => !v)}
      >
        Speed {replay.speed}×
      </button>
      <SpeedGroup
        speed={replay.speed}
        onChange={replay.setSpeed}
        id={`${uid}-speeds`}
        open={speedOpen}
      />

      <p className="sr-only-live" aria-live="polite" data-testid="replay-announce">
        {spoken}
      </p>
    </section>
  )
}
