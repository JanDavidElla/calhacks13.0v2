// Calls to the server's Evaluate flow, typed to match docs/api-contract.md
import type { Product } from '@/utils/page';

// The side panel calls the server directly; host_permissions in wxt.config.ts allows it
const SERVER = 'http://127.0.0.1:8000';

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
  if (!response.ok) throw new Error(await readError(response));
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
