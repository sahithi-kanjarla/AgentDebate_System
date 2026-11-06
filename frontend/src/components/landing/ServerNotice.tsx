import { Link } from 'react-router-dom'
import { useServerStatus } from '../../hooks/useServerStatus'

/** Says so when the free host is still starting; renders nothing once the server answers. */
export function ServerNotice() {
  const status = useServerStatus()
  if (status !== 'waking') return null
  return (
    <p role="status" className="text-sm text-ink-soft" data-testid="waking">
      Waking the server. The free host sleeps when idle, so this can take up to a minute. You can
      still{' '}
      <Link to="/app?tab=demo" className="font-medium underline">
        watch a demo
      </Link>
      .
    </p>
  )
}
