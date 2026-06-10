/**
 * Learn island mount logic.
 *
 * Dynamically imported by `main.ts` when a `[data-island="learn"]` element is
 * found. Unlike the game island, this one consumes server props: the analyze
 * endpoint and (on saved-result pages) an `initialAnalysis` to render directly.
 */
import { createRoot } from 'react-dom/client'
import { LearnCodebaseIsland } from './LearnCodebaseIsland'
import type { LearnIslandProps } from './types'

/**
 * Mount the LearnCodebaseIsland into the given element.
 *
 * @param element - DOM element (the data-island div) to render into.
 * @param props   - Boot props parsed from `data-props` (analyzeEndpoint and an
 *                  optional initialAnalysis).
 */
export function mount(element: HTMLElement, props: unknown): void {
  // Clear the server-rendered <noscript> fallback before hydrating.
  element.innerHTML = ''

  const root = createRoot(element)
  root.render(<LearnCodebaseIsland {...(props as LearnIslandProps)} />)
}
