import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { BANNER_KEY, PROVIDER_NAMES } from '../lib/demoNotice'
import { readStored, resetStoredMemory } from '../lib/safeStorage'
import { History } from '../pages/History'
import { Home } from '../pages/Home'
import { stubFetch } from '../test/http'
import { DemoBanner, DemoFooter, HistoryNotice, StartNotice } from './DemoNotice'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  window.localStorage.clear()
  resetStoredMemory()
})

const production = () => vi.stubEnv('PROD', true)

describe('demo notices in a development or test build', () => {
  it('renders nothing', () => {
    const { container } = render(
      <>
        <DemoBanner />
        <DemoFooter />
        <StartNotice />
        <HistoryNotice />
      </>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('leaves the real pages without any notice', async () => {
    stubFetch(() => ({ status: 200, body: [] }))
    render(
      <MemoryRouter initialEntries={['/history']}>
        <App />
      </MemoryRouter>,
    )
    await screen.findByText('No debates yet.', { exact: false })
    expect(screen.queryByText(/free-tier demo/i)).toBeNull()
    expect(screen.queryByText(/stored per browser/i)).toBeNull()
  })
})

describe('demo notices in a production build', () => {
  it('banner says: free tier, no personal data, third-party providers by name, slow or unavailable', () => {
    production()
    render(<DemoBanner />)
    const banner = screen.getByRole('region', { name: 'About this demo' })
    expect(banner).toHaveTextContent(/free-tier demo/i)
    expect(banner).toHaveTextContent(/slow or unavailable/i)
    expect(banner).toHaveTextContent(/personal or confidential/i)
    for (const name of PROVIDER_NAMES) expect(banner).toHaveTextContent(name)
    expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute('href', '#privacy')
  })

  it('can be dismissed, stays dismissed on the next visit, and the footer note remains', () => {
    production()
    const first = render(
      <>
        <DemoBanner />
        <DemoFooter />
      </>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByRole('region', { name: 'About this demo' })).toBeNull()
    expect(readStored(BANNER_KEY)).toBe('dismissed')
    expect(screen.getByRole('contentinfo')).toHaveTextContent(/personal or confidential/i)
    first.unmount()

    render(<DemoBanner />) // a later visit
    expect(screen.queryByRole('region', { name: 'About this demo' })).toBeNull()
  })

  it('still shows when storage is blocked', () => {
    production()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    render(<DemoBanner />)
    expect(screen.getByRole('region', { name: 'About this demo' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' })) // does not throw
    expect(screen.queryByRole('region', { name: 'About this demo' })).toBeNull()
    vi.restoreAllMocks()
  })

  it('footer: privacy anchor, providers, temporary storage, shared links, address use', () => {
    production()
    render(<DemoFooter />)
    const footer = screen.getByRole('contentinfo')
    expect(footer).toHaveAttribute('id', 'privacy')
    for (const name of PROVIDER_NAMES) expect(footer).toHaveTextContent(name)
    expect(footer).toHaveTextContent(/history is stored per\s+browser/i)
    expect(footer).toHaveTextContent(/anyone with a debate link can read that\s+debate/i)
    expect(footer).toHaveTextContent(
      /stored on\s+the demo's server and may be deleted when the host restarts/i,
    )
    expect(footer).toHaveTextContent(/not saved with your\s+debate/i)
  })

  it('shows the line beside the Start button and the History note', async () => {
    production()
    stubFetch(() => ({ status: 200, body: [] }))
    const home = render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText(/do not enter personal or confidential data/i)).toBeInTheDocument()
    home.unmount()

    render(
      <MemoryRouter initialEntries={['/history']}>
        <Routes>
          <Route path="/history" element={<History />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('note')).toHaveTextContent(
      /stored per browser.*anyone with a debate link can read that debate.*may\s+be deleted when the host restarts/is,
    )
  })

  it('the whole app has the banner before the header and the footer after the content', async () => {
    production()
    stubFetch(() => ({ status: 200, body: [] }))
    render(
      <MemoryRouter initialEntries={['/history']}>
        <App />
      </MemoryRouter>,
    )
    await screen.findByText('No debates yet.', { exact: false })
    expect(screen.getAllByRole('region', { name: 'About this demo' })).toHaveLength(1)
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })
})
