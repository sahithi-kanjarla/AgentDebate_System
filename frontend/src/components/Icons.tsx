import type { ReactNode } from 'react'
import type { Severity } from '../lib/types'

interface IconProps {
  size?: number
}

function Svg({ size = 16, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="shrink-0"
    >
      {children}
    </svg>
  )
}

/** Severity shapes: dot (low), triangle (medium), diamond with a mark (high). */
export function SeverityIcon({ severity, size }: IconProps & { severity: Severity }) {
  if (severity === 'low') {
    return (
      <Svg size={size}>
        <circle cx="8" cy="8" r="3.4" fill="currentColor" />
      </Svg>
    )
  }
  if (severity === 'medium') {
    return (
      <Svg size={size}>
        <path d="M8 2.6 14 13H2z" fill="currentColor" fillOpacity="0.18" />
        <path d="M8 6.6v3" />
        <path d="M8 11.4v.1" />
      </Svg>
    )
  }
  return (
    <Svg size={size}>
      <path d="M8 1.6 14.4 8 8 14.4 1.6 8z" fill="currentColor" fillOpacity="0.18" />
      <path d="M8 5v3.4" />
      <path d="M8 10.8v.1" />
    </Svg>
  )
}

export function CheckIcon({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="m3 8.5 3.2 3.2L13 4.6" />
    </Svg>
  )
}

export function SwapIcon({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M2.5 5.5h10M10 3l2.5 2.5L10 8" />
      <path d="M13.5 10.5h-10M6 8l-2.5 2.5L6 13" />
    </Svg>
  )
}

/** Persona glyphs: steps (Solver), magnifier (Skeptic), tick in a box (Fact-Checker). */
export function PersonaGlyph({ persona, size }: IconProps & { persona: string }) {
  const key = persona.toLowerCase()
  if (key.includes('solver')) {
    return (
      <Svg size={size}>
        <path d="M2 13h3.5V9.5H9V6h5" />
      </Svg>
    )
  }
  if (key.includes('skeptic')) {
    return (
      <Svg size={size}>
        <circle cx="7" cy="7" r="4.2" />
        <path d="m10.2 10.2 3.6 3.6" />
      </Svg>
    )
  }
  if (key.includes('fact')) {
    return (
      <Svg size={size}>
        <rect x="2.2" y="2.2" width="11.6" height="11.6" rx="1.5" />
        <path d="m5.2 8.2 2 2 3.6-4" />
      </Svg>
    )
  }
  return (
    <Svg size={size}>
      <circle cx="8" cy="8" r="5.6" />
    </Svg>
  )
}
