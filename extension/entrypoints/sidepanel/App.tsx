import { useEffect, useState } from 'react';
import { GET_PRODUCT, type PageProduct } from '@/utils/page';

type PageState =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'product'; product: PageProduct };

async function readActiveTab(): Promise<PageProduct | null> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === undefined) return null;
  try {
    return await browser.tabs.sendMessage(tab.id, GET_PRODUCT);
  } catch {
    // No content script answered: not an Amazon page, or it was opened before the extension loaded
    return null;
  }
}

function App() {
  const [page, setPage] = useState<PageState>({ status: 'loading' });

  useEffect(() => {
    const refresh = async () => {
      const product = await readActiveTab();
      setPage(product ? { status: 'product', product } : { status: 'none' });
    };
    const onUpdated = (_tabId: number, change: { status?: string }) => {
      if (change.status === 'complete') refresh();
    };

    refresh();
    // Follow the user as they switch tabs or a page finishes loading
    browser.tabs.onActivated.addListener(refresh);
    browser.tabs.onUpdated.addListener(onUpdated);
    return () => {
      browser.tabs.onActivated.removeListener(refresh);
      browser.tabs.onUpdated.removeListener(onUpdated);
    };
  }, []);

  return (
    <main>
      <h1>Fit Check</h1>
      {page.status === 'loading' && <p>Reading this page…</p>}
      {page.status === 'none' && <p>Open an Amazon product page. If one is already open, reload it.</p>}
      {page.status === 'product' && (
        <section>
          <p>{page.product.title}</p>
          <p>ASIN: {page.product.asin}</p>
        </section>
      )}
    </main>
  );
}

export default App;
