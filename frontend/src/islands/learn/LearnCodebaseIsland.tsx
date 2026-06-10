/**
 * LearnCodebaseIsland — the interactive UI for the /learn feature.
 *
 * Responsibilities:
 * - Render a URL form and POST it to the configured analyze endpoint.
 * - Show distinct loading / error / result states.
 * - Render a saved analysis passed via `initialAnalysis` WITHOUT re-fetching
 *   (saved-result pages must render server-side data directly).
 * - Present the path as student-friendly sections with a prominent reading
 *   order, each step carrying a short reason/goal.
 *
 * Safety: every repository-provided string (descriptions, paths, reasons) is
 * rendered as React text — never via `dangerouslySetInnerHTML` — so a repo
 * cannot inject markup into the page.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import type {
  AnalyzeRepositoryError,
  AnalyzeRepositoryResponse,
  LearnIslandProps,
  RepositoryAnalysisPayload,
} from './types'

const PLACEHOLDER = 'https://github.com/python/cpython/tree/main/Lib/idlelib'

type Status = 'idle' | 'loading' | 'error' | 'success'

export function LearnCodebaseIsland({ analyzeEndpoint, initialAnalysis }: LearnIslandProps) {
  const [url, setUrl] = useState(initialAnalysis?.repository.normalizedUrl ?? '')
  const [status, setStatus] = useState<Status>(initialAnalysis ? 'success' : 'idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<RepositoryAnalysisPayload | null>(
    initialAnalysis ?? null,
  )
  const [cached, setCached] = useState<boolean>(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) {
      setStatus('error')
      setErrorMessage('Enter a public GitHub repository URL.')
      return
    }

    setStatus('loading')
    setErrorMessage(null)

    try {
      const response = await fetch(analyzeEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repositoryUrl: trimmed }),
      })
      const data = (await response.json()) as
        | AnalyzeRepositoryResponse
        | AnalyzeRepositoryError

      if (!response.ok || 'error' in data) {
        const message =
          'error' in data ? data.error.message : 'Something went wrong. Please try again.'
        setStatus('error')
        setErrorMessage(message)
        return
      }

      setAnalysis(data.analysis)
      setCached(data.cached)
      setStatus('success')
    } catch {
      setStatus('error')
      setErrorMessage('Could not reach the analyzer. Check your connection and try again.')
    }
  }

  return (
    <div className="w-full">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          name="repositoryUrl"
          aria-label="GitHub repository URL"
          placeholder={PLACEHOLDER}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={status === 'loading'}
          className="rounded bg-gray-800 px-4 py-2 text-sm font-medium text-white hover:bg-gray-900 disabled:opacity-50"
        >
          {status === 'loading' ? 'Analyzing…' : 'Generate learning path'}
        </button>
      </form>

      {status === 'loading' && (
        <p role="status" className="mt-4 text-sm text-gray-600">
          Analyzing repository…
        </p>
      )}

      {status === 'error' && errorMessage && (
        <p role="alert" className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorMessage}
        </p>
      )}

      {status === 'success' && analysis && (
        <AnalysisView analysis={analysis} cached={cached} />
      )}
    </div>
  )
}

function AnalysisView({
  analysis,
  cached,
}: {
  analysis: RepositoryAnalysisPayload
  cached: boolean
}) {
  const { repository, sections, readingOrder, keyDirectories, reflectionPrompts } = analysis

  return (
    <section className="mt-8 flex flex-col gap-8">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold text-gray-800">{repository.displayName}</h2>
          {cached && (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
              cached result
            </span>
          )}
        </div>
        {repository.description && (
          <p className="mt-1 text-gray-600">{repository.description}</p>
        )}
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-500">
          {repository.language && (
            <div className="flex gap-1">
              <dt className="font-medium">Language:</dt>
              <dd>{repository.language}</dd>
            </div>
          )}
          <div className="flex gap-1">
            <dt className="font-medium">Branch:</dt>
            <dd>{repository.requestedRef}</dd>
          </div>
          <div className="flex gap-1">
            <dt className="font-medium">Commit:</dt>
            <dd>{repository.commitSha.slice(0, 8)}</dd>
          </div>
          <a href={repository.htmlUrl} className="text-blue-600 hover:underline">
            View on GitHub
          </a>
        </dl>
      </header>

      {readingOrder.length > 0 && (
        <div data-testid="reading-order">
          <h3 className="mb-3 text-xl font-semibold text-gray-800">Suggested reading order</h3>
          <ol className="flex flex-col gap-3">
            {readingOrder.map((step) => (
              <li key={step.step} className="rounded border border-gray-200 bg-white p-4">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold text-gray-800">Step {step.step}:</span>
                  <span className="font-medium text-gray-800">{step.title}</span>
                </div>
                <p className="mt-1 text-sm text-gray-600">{step.goal}</p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {step.paths.map((path) => (
                    <li key={path}>
                      <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700">
                        {path}
                      </code>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </div>
      )}

      {keyDirectories.length > 0 && (
        <div>
          <h3 className="mb-3 text-xl font-semibold text-gray-800">Key directories</h3>
          <ul className="flex flex-wrap gap-2">
            {keyDirectories.map((dir) => (
              <li key={dir}>
                <code className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-700">{dir}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {sections.map((section) => (
        <div key={section.id} data-testid={`section-${section.id}`}>
          <h3 className="mb-1 text-xl font-semibold text-gray-800">{section.title}</h3>
          <p className="mb-3 text-sm text-gray-600">{section.summary}</p>
          <ul className="flex flex-col gap-2">
            {section.items.map((item) => (
              <li key={item.path} className="rounded border border-gray-200 bg-white p-3">
                <a
                  href={item.url}
                  className="font-mono text-sm text-blue-600 hover:underline"
                >
                  {item.path}
                </a>
                <p className="mt-1 text-sm text-gray-600">{item.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {reflectionPrompts.length > 0 && (
        <div>
          <h3 className="mb-3 text-xl font-semibold text-gray-800">Reflection prompts</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700">
            {reflectionPrompts.map((prompt) => (
              <li key={prompt}>{prompt}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
