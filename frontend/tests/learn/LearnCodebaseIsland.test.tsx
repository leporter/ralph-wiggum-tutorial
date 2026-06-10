/**
 * Component tests for the LearnCodebaseIsland.
 *
 * Why these matter: they pin the student-facing behavior contract — a valid
 * submission POSTs to the configured endpoint and renders ordered sections;
 * errors surface an actionable message; a loading state appears; an
 * `initialAnalysis` renders WITHOUT a network call (saved-result pages); file
 * links and reading-order labels are visible; and repository-provided strings
 * are rendered as inert text, never as executable markup (XSS guard).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LearnCodebaseIsland } from '@/islands/learn/LearnCodebaseIsland'
import type { RepositoryAnalysisPayload } from '@/islands/learn/types'

const ENDPOINT = '/learn/analyze'

function makeAnalysis(overrides: Partial<RepositoryAnalysisPayload> = {}): RepositoryAnalysisPayload {
  return {
    id: 'abc-123',
    repository: {
      owner: 'python',
      repo: 'cpython',
      displayName: 'python/cpython/Lib/idlelib',
      normalizedUrl: 'https://github.com/python/cpython/tree/main/Lib/idlelib',
      htmlUrl: 'https://github.com/python/cpython',
      defaultBranch: 'main',
      requestedRef: 'main',
      scopePath: 'Lib/idlelib',
      commitSha: 'deadbeefcafe',
      description: 'The Python programming language',
      language: 'Python',
    },
    keyDirectories: ['Lib/idlelib'],
    sections: [
      {
        id: 'entry-points',
        title: 'Start with the entry points',
        summary: 'Why this step matters.',
        items: [
          {
            path: 'Lib/idlelib/idle.py',
            reason: 'Likely IDLE startup entry point.',
            url: 'https://github.com/python/cpython/blob/deadbeefcafe/Lib/idlelib/idle.py',
          },
        ],
      },
    ],
    readingOrder: [
      { step: 1, title: 'Read the README', paths: ['Lib/idlelib/README.txt'], goal: 'Understand the package.' },
    ],
    reflectionPrompts: ['What file starts IDLE?'],
    createdAt: '2026-06-09T23:15:44Z',
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('LearnCodebaseIsland', () => {
  it('submits to the configured endpoint and renders ordered sections', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ analysis: makeAnalysis(), cached: false }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<LearnCodebaseIsland analyzeEndpoint={ENDPOINT} />)
    fireEvent.change(screen.getByLabelText('GitHub repository URL'), {
      target: { value: 'https://github.com/python/cpython/tree/main/Lib/idlelib' },
    })
    fireEvent.click(screen.getByRole('button', { name: /generate learning path/i }))

    await waitFor(() => expect(screen.getByText(/Suggested reading order/i)).toBeInTheDocument())

    expect(fetchMock).toHaveBeenCalledWith(
      ENDPOINT,
      expect.objectContaining({ method: 'POST' }),
    )
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.repositoryUrl).toContain('github.com/python/cpython')
    // Reading-order label + section + file link are visible.
    expect(screen.getByText(/Step 1:/)).toBeInTheDocument()
    expect(screen.getByText('Start with the entry points')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Lib/idlelib/idle.py' })
    expect(link).toHaveAttribute('href', expect.stringContaining('/blob/deadbeefcafe/'))
  })

  it('shows a loading state during submission', async () => {
    let resolve!: (v: unknown) => void
    const fetchMock = vi.fn().mockReturnValue(new Promise((r) => (resolve = r)))
    vi.stubGlobal('fetch', fetchMock)

    render(<LearnCodebaseIsland analyzeEndpoint={ENDPOINT} />)
    fireEvent.change(screen.getByLabelText('GitHub repository URL'), {
      target: { value: 'https://github.com/python/cpython' },
    })
    fireEvent.click(screen.getByRole('button', { name: /generate learning path/i }))

    expect(await screen.findByRole('status')).toHaveTextContent(/Analyzing/i)
    resolve({ ok: true, json: async () => ({ analysis: makeAnalysis(), cached: false }) })
    // Let the resolved promise flush so the final state update is wrapped.
    await screen.findByText(/Suggested reading order/i)
  })

  it('shows an actionable message on backend error', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: { code: 'invalid_repository_url', message: 'Enter a public GitHub repository URL.' } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<LearnCodebaseIsland analyzeEndpoint={ENDPOINT} />)
    fireEvent.change(screen.getByLabelText('GitHub repository URL'), {
      target: { value: 'http://bad' },
    })
    fireEvent.click(screen.getByRole('button', { name: /generate learning path/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a public GitHub repository URL.')
  })

  it('renders initialAnalysis without making a POST', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(
      <LearnCodebaseIsland analyzeEndpoint={ENDPOINT} initialAnalysis={makeAnalysis()} />,
    )

    expect(screen.getByText('python/cpython/Lib/idlelib')).toBeInTheDocument()
    expect(screen.getByText(/Suggested reading order/i)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('renders repository-provided strings as inert text (no HTML injection)', () => {
    const malicious = makeAnalysis({
      repository: {
        ...makeAnalysis().repository,
        description: '<img src=x onerror="window.__pwned=true">',
      },
    })
    render(<LearnCodebaseIsland analyzeEndpoint={ENDPOINT} initialAnalysis={malicious} />)

    // The string is shown verbatim as text; no <img> element is created.
    expect(screen.getByText('<img src=x onerror="window.__pwned=true">')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })
})
