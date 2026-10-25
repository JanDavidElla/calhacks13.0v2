// Calls to the server's Evaluate flow, typed to match docs/api-contract.md
import type { Product } from '@/utils/page';

// The side panel calls the server directly; host_permissions in wxt.config.ts allows it
const SERVER = 'http://127.0.0.1:8000';

// A response the server refused; for /api/plan a 400 carries a question or reason for the user
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export type PlannedPart = {
  category: string;
  search_query: string;
  max_price: number;
  search_url: string;
};

export type Plan = {
  transcript: string;
  budget: number;
  budget_estimated: boolean;
  parts: PlannedPart[];
};

export type SetupEntry = {
  category: string;
  product: Product;
};

export type Check = {
  kind: 'match' | 'compatibility' | 'budget' | 'reviews';
  status: 'pass' | 'warn' | 'fail';
  parts: string[];
  reason: string;
  points: number;
};

export type Evaluation = {
  score: number;
  checks: Check[];
};

export type Alternative = Evaluation & {
  product: Product;
  price_difference: number | null;
};

// The same product at another store; url is Google Shopping's page, which links to the store
export type Offer = {
  store: string;
  title: string;
  price: number;
  url: string;
};

export type EvaluateRequest = {
  request: string;
  category: string;
  product: Product;
  setup: SetupEntry[];
  max_price: number;
};

export type AlternativesRequest = {
  request: string;
  category: string;
  search_query: string;
  max_price: number;
  setup: SetupEntry[];
  product?: Product;
};

export function createPlan(text: string): Promise<Plan> {
  const form = new FormData();
  form.set('text', text);
  return post('/api/plan', form);
}

export function evaluate(body: EvaluateRequest): Promise<Evaluation> {
  return post('/api/evaluate', JSON.stringify(body));
}

export async function findAlternatives(body: AlternativesRequest): Promise<Alternative[]> {
  const result = await post<{ alternatives: Alternative[] }>(
    '/api/alternatives',
    JSON.stringify(body),
  );
  return result.alternatives;
}

// Cheapest first
export async function findOtherStores(product: Product): Promise<Offer[]> {
  const result = await post<{ offers: Offer[] }>('/api/other-stores', JSON.stringify({ product }));
  return result.offers;
}

// Throws an Error whose message can be shown to the user
async function post<T>(path: string, body: FormData | string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${SERVER}${path}`, {
      method: 'POST',
      // FormData sets its own multipart Content-Type
      headers: typeof body === 'string' ? { 'Content-Type': 'application/json' } : undefined,
      body,
    });
  } catch {
    throw new Error(`Can't reach the server at ${SERVER}. Is it running?`);
  }
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.json();
}

async function readError(response: Response): Promise<string> {
  try {
    const { detail } = await response.json();
    // 422s list each invalid field instead of a single message
    if (typeof detail === 'string') return detail;
  } catch {
    // Not JSON, so fall back to the status below
  }
  return `Request failed (${response.status})`;
}
