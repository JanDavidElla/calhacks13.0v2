import { useEffect, useState } from 'react';

// The item's value, kept in sync with storage; undefined until it has loaded
export function useStoredItem<T>(item: WxtStorageItem<T, Record<string, unknown>>): T | undefined {
  const [value, setValue] = useState<T>();

  useEffect(() => {
    void item.getValue().then(setValue);
    return item.watch(setValue);
  }, [item]);

  return value;
}
