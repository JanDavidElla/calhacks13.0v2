import { useEffect, useState } from 'react';
import { replan, type Plan, type Replan } from '@/utils/api';
import type { ShortlistEntry } from '@/utils/storage';

export type ReplanState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; replan: Replan }
  | { status: 'failed' };

// Updates the plan for what's on the shortlist: skips parts its products already take care of,
// and splits what's left of the budget across the rest
export function useReplan(plan: Plan | null | undefined, setup: ShortlistEntry[]): ReplanState {
  const [state, setState] = useState<ReplanState>({ status: 'idle' });
  // Which product fills which part; a new object for the same shortlist doesn't ask again
  const setupKey = setup.map((entry) => `${entry.category}:${entry.product.asin}`).join();

  useEffect(() => {
    // With nothing chosen the plan stays as it was, so there's nothing to ask
    if (!plan || setup.length === 0) {
      setState({ status: 'idle' });
      return;
    }
    // Ignore an answer that arrives after the shortlist changed again
    let current = true;
    setState({ status: 'loading' });
    replan(plan, setup)
      .then((result) => current && setState({ status: 'done', replan: result }))
      // The list falls back to the plan as first made, which is still a fair guide
      .catch(() => current && setState({ status: 'failed' }));
    return () => {
      current = false;
    };
  }, [plan?.transcript, plan?.budget, setupKey]);

  return state;
}
