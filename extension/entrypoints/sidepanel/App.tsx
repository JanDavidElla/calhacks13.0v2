import { useEffect, useState } from 'react';
import { GET_PRODUCT, type PageProduct } from '@/utils/page';

type PageState =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'product'; product: PageProduct };

type DisclosureTone = 'good' | 'bad' | 'warn';

type DisclosureProps = {
  title: string;
  detail: string;
  tone: DisclosureTone;
};

async function readActiveTab(): Promise<PageProduct | null> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === undefined) return null;

  try {
    return await browser.tabs.sendMessage(tab.id, GET_PRODUCT);
  } catch {
    return null;
  }
}

function Disclosure({ title, detail, tone }: DisclosureProps) {
  const [open, setOpen] = useState(true);

  return (
    <button
      className={`disclosure disclosure-${tone}`}
      onClick={() => setOpen((value) => !value)}
      aria-expanded={open}
    >
      <span className="disclosure-heading">
        <span>{title}</span>
        <span className={`chevron ${open ? '' : 'chevron-closed'}`} aria-hidden="true">
         ⌄
        </span>
      </span>
      {open && <span className="disclosure-detail">{detail}</span>}
    </button>
  );
}

function App() {
  const [page, setPage] = useState<PageState>({ status: 'loading' });
  const [tab, setTab] = useState<'product' | 'shortlist'>('product');

  useEffect(() => {
    const refresh = async () => {
      const product = await readActiveTab();
      setPage(product ? { status: 'product', product } : { status: 'none' });
    };
    const onUpdated = (_tabId: number, change: { status?: string }) => {
      if (change.status === 'complete') void refresh();
    };

    void refresh();
    browser.tabs.onActivated.addListener(refresh);
    browser.tabs.onUpdated.addListener(onUpdated);
    return () => {
      browser.tabs.onActivated.removeListener(refresh);
      browser.tabs.onUpdated.removeListener(onUpdated);
    };
  }, []);

  const product = page.status === 'product' ? page.product : null;
  const productTitle = product?.title ?? 'Canvas 32 4K';

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-icon">✓</span>
          <h1>Khai&apos;s CTO</h1>
        </div>
        <div className="header-actions">
          <button className="icon-button" aria-label="Open in new window">
            ↗
          </button>
          <button className="icon-button" aria-label="Close">
            ×
          </button>
        </div>
      </header>

      <section className="project-bar">
        <div className="project-heading">
          <h2>Home office</h2>
          <div className="project-actions">
            <span className="save-status">
              <span className="status-dot">!</span>
              Not saved
            </span>
            <button aria-label="Edit project">✎</button>
            <button aria-label="Save project">♡</button>
          </div>
        </div>
        <div className="tabs" role="tablist" aria-label="Project view">
          <button
            className={tab === 'product' ? 'tab tab-active' : 'tab'}
            onClick={() => setTab('product')}
            role="tab"
            aria-selected={tab === 'product'}
          >
            This product
          </button>
          <button
            className={tab === 'shortlist' ? 'tab tab-active' : 'tab'}
            onClick={() => setTab('shortlist')}
            role="tab"
            aria-selected={tab === 'shortlist'}
          >
            Shortlist · 6
          </button>
        </div>
      </section>

      <section className="content">
        <div className="section-heading">
          <span className="section-icon">☷</span>
          <h2>CTO</h2>
        </div>

        {tab === 'product' ? (
          <div className="fit-card">
            <div className="score-card">
              <div className="score">68%</div>
              <p className="score-label">Conditional fit</p>
              <p className="score-summary">Swap arm + dock to fit this monitor.</p>
              <div className="product-row">
                <strong>{productTitle}</strong>
                <span>$419</span>
              </div>
              {page.status === 'none' && (
                <p className="page-hint">
                  Open an Amazon product page to evaluate the item you are viewing.
                </p>
              )}
              {product && <p className="asin">ASIN: {product.asin}</p>}
            </div>
            <div className="disclosures">
              <Disclosure
                tone="good"
                title="Pros"
                detail="More room · 4K at 60 Hz · VESA 100"
              />
              <Disclosure
                tone="bad"
                title="Cons · 2 incompatible"
                detail="Lift S load limit exceeded · D1: 4K / 30 Hz"
              />
              <Disclosure
                tone="warn"
                title="Missing spec · 1 unverified"
                detail="USB-C charging not listed"
              />
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <strong>6 shortlisted products</strong>
            <p>Open the project plan to compare your saved options.</p>
          </div>
        )}
      </section>

      <footer className="summary">
        <div className="summary-card">
          <div className="summary-line">
            <span>Setup total</span>
            <strong>$737</strong>
          </div>
          <p>Includes compatible arm + dock</p>
          <hr />
          <div className="summary-line summary-detail">
            <span>Budget remaining</span>
            <strong>$113</strong>
          </div>
          <div className="summary-line summary-detail">
            <span>Change from current</span>
            <span>+$260</span>
          </div>
        </div>
        <button className="plan-link">Open project plan <span>→</span></button>
      </footer>
    </main>
  );
}

export default App;
