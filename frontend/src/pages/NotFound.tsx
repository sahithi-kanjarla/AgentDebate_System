import { Link } from 'react-router-dom'
import { PageTitle } from '../components/SiteChrome'

export function NotFound() {
  return (
    <div className="max-w-xl">
      <PageTitle title="Page not found">There is nothing at this address.</PageTitle>
      <Link to="/" className="font-medium text-brass underline underline-offset-2">
        Go to the start page
      </Link>
    </div>
  )
}
