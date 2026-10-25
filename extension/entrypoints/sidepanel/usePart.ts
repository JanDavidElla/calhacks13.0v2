import { useEffect, useState } from 'react';
import { classifyProduct, type Plan } from '@/utils/api';
import { matchCategory, sureCategory } from '@/utils/category';
import type { Product } from '@/utils/page';

export type PartState =
  | { status: 'loading' }
  // category is null when the product isn't any part of the plan
  | { status: 'done'; category: string | null }
  | { status: 'error'; message: string };

// Which part of the plan the product is. A clear title settles it at once; otherwise Claude is
// asked, since sales words like "ergonomic" and "office" make titles look like the wrong part
export function usePart(product: Product | null, plan: Plan | null | undefined): PartState {
  const sure = product && plan ? sureCategory(product.title, plan.parts) : null;
  const key = product && plan ? `${plan.transcript}|${product.asin}|${product.title}` : '';
  // Kept with the product it's for, so the next product never starts with this one's answer
  const [asked, setAsked] = useState<{ key: string; state: PartState } | null>(null);

  useEffect(() => {
    if (!product || !plan || sure) return;
    // Ignore an answer that arrives after the user moved on
    let current = true;
    classifyProduct(plan, product)
      .then((category) => current && setAsked({ key, state: { status: 'done', category } }))
      .catch((error: Error) => {
        if (!current) return;
        // Claude couldn't be asked, so fall back to the title's best match when there is one
        const guess = matchCategory(product.title, plan.parts);
        const state: PartState = guess
          ? { status: 'done', category: guess }
          : { status: 'error', message: error.message };
        setAsked({ key, state });
      });
    return () => {
      current = false;
    };
  }, [key, sure]);

  if (sure) return { status: 'done', category: sure };
  return asked?.key === key ? asked.state : { status: 'loading' };
}
