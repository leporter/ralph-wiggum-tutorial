/**
 * Types for the codebase-learning island.
 *
 * Field names mirror the backend payload (see
 * `src/app/schemas/repository_analysis.py`) exactly so the island can render
 * server data with no ad-hoc transforms — the contract is the single source of
 * truth shared by both sides.
 */

export type RepositorySummary = {
  owner: string
  repo: string
  displayName: string
  normalizedUrl: string
  htmlUrl: string
  defaultBranch: string
  requestedRef: string
  scopePath: string
  commitSha: string
  description: string | null
  language: string | null
}

export type LearningPathItem = {
  path: string
  reason: string
  url: string
}

export type LearningPathSection = {
  id: string
  title: string
  summary: string
  items: LearningPathItem[]
}

export type ReadingOrderStep = {
  step: number
  title: string
  paths: string[]
  goal: string
}

export type RepositoryAnalysisPayload = {
  id: string
  repository: RepositorySummary
  keyDirectories: string[]
  sections: LearningPathSection[]
  readingOrder: ReadingOrderStep[]
  reflectionPrompts: string[]
  createdAt: string
}

export type AnalyzeRepositoryResponse = {
  analysis: RepositoryAnalysisPayload
  cached: boolean
}

export type AnalyzeRepositoryError = {
  error: {
    code: string
    message: string
  }
}

export type LearnIslandProps = {
  analyzeEndpoint: string
  initialAnalysis?: RepositoryAnalysisPayload
}
