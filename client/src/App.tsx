import { useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Product = {
  asin: string
  title: string
  price: number
  url: string
  image: string | null
  stars: number | null
  details: string | null
}

type PlannedPart = {
  category: string
  search_query: string
  max_price: number
  search_url: string
}

type PlanResponse = {
  transcript: string
  budget: number
  budget_estimated: boolean
  parts: PlannedPart[]
}

type ScoreCheck = {
  kind: string
  status: 'pass' | 'warn' | 'fail'
  parts: string[]
  reason: string
  points: number
}

type Alternative = {
  product: Product
  score: number
  checks: ScoreCheck[]
  price_difference: number | null
}

type AlternativesResponse = {
  alternatives: Alternative[]
}

type PartResults = Record<string, Alternative[]>

async function readApiError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    if (body.detail) {
      return body.detail
    }
  } catch {
    // Use the status below when the server doesn't return JSON.
  }
  return `Request failed (${response.status})`
}

async function createPlan(request: string): Promise<PlanResponse> {
  const form = new FormData()
  form.set('text', request)
  const response = await fetch('/api/plan', { method: 'POST', body: form })
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  return (await response.json()) as PlanResponse
}

async function findAlternatives(
  request: string,
  part: PlannedPart,
): Promise<Alternative[]> {
  const response = await fetch('/api/alternatives', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      request,
      category: part.category,
      search_query: part.search_query,
      max_price: part.max_price,
      setup: [],
    }),
  })
  if (!response.ok) {
    throw new Error(await readApiError(response))
  }
  const result = (await response.json()) as AlternativesResponse
  return result.alternatives
}

function App() {
  const [request, setRequest] = useState('')
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [results, setResults] = useState<PartResults>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!request.trim()) {
      setError('Tell us what you want to shop for.')
      return
    }

    setLoading(true)
    setError(null)
    setPlan(null)
    setResults({})

    try {
      const nextPlan = await createPlan(request.trim())
      setPlan(nextPlan)
      const entries = await Promise.all(
        nextPlan.parts.map(async (part) => [
          part.category,
          await findAlternatives(nextPlan.transcript, part),
        ] as const),
      )
      setResults(Object.fromEntries(entries))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">SHOPPING, WITHOUT THE GUESSWORK</p>
        <h1>Build a better basket.</h1>
        <p className="hero-copy">
          Describe what you need and we&apos;ll turn it into a plan with products
          scored for fit, budget, and reviews.
        </p>
        <form className="request-form" onSubmit={handleSubmit}>
          <label htmlFor="shopping-request">What are you shopping for?</label>
          <div className="request-row">
            <input
              id="shopping-request"
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              placeholder="A quiet gaming PC for $1,200"
              disabled={loading}
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Building…' : 'Build plan'}
            </button>
          </div>
        </form>
        {error && <p className="error-message" role="alert">{error}</p>}
      </header>

      {plan && (
        <section className="results" aria-live="polite">
          <div className="results-heading">
            <div>
              <p className="eyebrow">YOUR PLAN</p>
              <h2>{plan.transcript}</h2>
            </div>
            <p className="budget">
              {plan.budget_estimated ? 'Estimated budget' : 'Budget'}:{' '}
              <strong>${plan.budget.toFixed(0)}</strong>
            </p>
          </div>
          <div className="part-grid">
            {plan.parts.map((part) => {
              const alternatives = results[part.category] ?? []
              return (
                <article className="part-card" key={part.category}>
                  <div className="part-heading">
                    <div>
                      <p className="eyebrow">PART</p>
                      <h3>{part.category}</h3>
                    </div>
                    <span>Up to ${part.max_price.toFixed(0)}</span>
                  </div>
                  <p className="search-query">{part.search_query}</p>
                  {loading && alternatives.length === 0 ? (
                    <p className="muted">Finding and scoring products…</p>
                  ) : alternatives.length === 0 ? (
                    <p className="muted">No products scored higher than the baseline.</p>
                  ) : (
                    <div className="product-list">
                      {alternatives.map((alternative) => (
                        <a
                          className="product"
                          href={alternative.product.url}
                          key={alternative.product.asin}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {alternative.product.image ? (
                            <img src={alternative.product.image} alt="" />
                          ) : (
                            <div className="image-placeholder" aria-hidden="true" />
                          )}
                          <div className="product-info">
                            <h4>{alternative.product.title}</h4>
                            <p className="product-meta">
                              ${alternative.product.price.toFixed(2)}
                              {alternative.product.stars !== null &&
                                ` · ${alternative.product.stars.toFixed(1)}★`}
                            </p>
                            <span className={`score score-${alternative.score >= 80 ? 'good' : alternative.score >= 50 ? 'warn' : 'bad'}`}>
                              {alternative.score}/100
                            </span>
                            <p className="check-summary">
                              {alternative.checks.find((check) => check.status !== 'pass')?.reason ??
                                'Strong fit for this part.'}
                            </p>
                          </div>
                        </a>
                      ))}
                    </div>
                  )}
                  <a className="search-link" href={part.search_url} target="_blank" rel="noreferrer">
                    Browse all on Amazon →
                  </a>
                </article>
              )
            })}
          </div>
        </section>
      )}
    </main>
  )
}

export default App
