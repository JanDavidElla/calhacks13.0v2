// The user's state lives here: the server stores nothing between requests
import { useEffect, useState } from 'react';
import type { Plan, SetupEntry } from '@/utils/api';

export const planItem = storage.defineItem<Plan | null>('local:plan', { fallback: null });

export const setupItem = storage.defineItem<SetupEntry[]>('local:setup', { fallback: [] });

// The item's value, kept in sync with storage; undefined until it has loaded
export function useStoredItem<T>(item: WxtStorageItem<T, Record<string, unknown>>): T | undefined {
  const [value, setValue] = useState<T>();

  useEffect(() => {
    void item.getValue().then(setValue);
    return item.watch(setValue);
  }, [item]);

  return value;
}
