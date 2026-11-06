import type { ReactNode } from 'react'
import { useInView } from '../../hooks/useInView'

/** Fades its children in once, as they scroll into view. Plain content when motion is reduced (CSS). */
export function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const [ref, seen] = useInView<HTMLDivElement>()
  return (
    <div ref={ref} className={`reveal ${seen ? 'is-in' : ''} ${className}`}>
      {children}
    </div>
  )
}
