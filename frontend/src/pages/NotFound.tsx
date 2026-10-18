import { Link } from 'react-router-dom'

export function NotFound() {
  return (
    <div className="max-w-xl">
      <h1 className="text-3xl">Page not found</h1>
      <p className="mt-2 text-ink-soft">There is nothing at this address.</p>
      <p className="mt-4">
        <Link to="/" className="font-medium text-brass underline">
          Go to the start page
        </Link>
      </p>
    </div>
  )
}
