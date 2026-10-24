import { useEffect, useState } from 'react';
import type { Check, Plan, PlannedPart, SetupEntry } from '@/utils/api';
import { GET_PRODUCT, type Product } from '@/utils/page';
import { planItem, setupItem, useStoredItem } from '@/utils/storage';
import RequestForm from './RequestForm';
import { guessCategory, useEvaluation, type EvaluationState } from './useEvaluation';

type PageState =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'product'; product: Product };

type DisclosureTone = 'good' | 'bad' | 'warn';

type DisclosureProps = {
  title: string;
  detail: string;
  tone: DisclosureTone;
};

async function readActiveTab(): Promise<Product | null> {
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

function scoreLabel(score: number): string {
  if (score >= 80) return 'Great fit';
  if (score >= 50) return 'Conditional fit';
  return 'Poor fit';
}

function reasons(checks: Check[]): string {
  return checks.map((check) => check.reason).join(' · ');
}

type ScoreCardProps = {
  product: Product;
  parts: PlannedPart[];
  category: string;
  onCategoryChange: (category: string) => void;
  state: EvaluationState;
};

function ScoreCard({ product, parts, category, onCategoryChange, state }: ScoreCardProps) {
  const checks = state.status === 'done' ? state.evaluation.checks : [];
  // The worst problem is the one-line summary
  const worst =
    checks.find((check) => check.status === 'fail') ?? checks.find((check) => check.status === 'warn');

  return (
    <div className="score-card">
      {state.status === 'loading' && (
        <>
          <div className="score">…</div>
          <p className="score-label">Analyzing</p>
          <p className="score-summary">Checking it against your project.</p>
        </>
      )}
      {state.status === 'error' && (
        <>
          <div className="score">?</div>
          <p className="score-label">Couldn&apos;t analyze</p>
          <p className="score-summary">{state.message}</p>
        </>
      )}
      {state.status === 'done' && (
        <>
          <div className="score">{state.evaluation.score}%</div>
          <p className="score-label">{scoreLabel(state.evaluation.score)}</p>
          <p className="score-summary">{worst?.reason ?? 'Fits your project.'}</p>
        </>
      )}
      <div className="product-row">
        <strong>{product.title}</strong>
        <span>${product.price.toFixed(2)}</span>
      </div>
      <label className="page-hint">
        Scored as{' '}
        <select value={category} onChange={(event) => onCategoryChange(event.target.value)}>
          {parts.map((part) => (
            <option key={part.category}>{part.category}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

type ProductFitProps = {
  product: Product;
  plan: Plan;
  setup: SetupEntry[];
};

// Analyzes the product as soon as its page opens; the parent keys it by ASIN
function ProductFit({ product, plan, setup }: ProductFitProps) {
  const [category, setCategory] = useState(() => guessCategory(product.title, plan.parts));
  const part = plan.parts.find((candidate) => candidate.category === category) ?? plan.parts[0];
  const state = useEvaluation(product, plan.transcript, part, setup);
  const checks = state.status === 'done' ? state.evaluation.checks : [];
  const pros = checks.filter((check) => check.status === 'pass');
  const cons = checks.filter((check) => check.status === 'fail');
  const missing = checks.filter((check) => check.status === 'warn');
  const shortlisted = setup.some((entry) => entry.product.asin === product.asin);

  async function addToShortlist() {
    // One product per part: adding replaces what filled this part before
    const others = setup.filter((entry) => entry.category !== category);
    await setupItem.setValue([...others, { category, product }]);
  }

  return (
    <div className="fit-card">
      <ScoreCard
        product={product}
        parts={plan.parts}
        category={category}
        onCategoryChange={setCategory}
        state={state}
      />
      <div className="disclosures">
        {pros.length > 0 && <Disclosure tone="good" title="Pros" detail={reasons(pros)} />}
        {cons.length > 0 && (
          <Disclosure
            tone="bad"
            title={`Cons · ${cons.length} ${cons.length === 1 ? 'issue' : 'issues'}`}
            detail={reasons(cons)}
          />
        )}
        {missing.length > 0 && (
          <Disclosure
            tone="warn"
            title={`Missing spec · ${missing.length} unverified`}
            detail={reasons(missing)}
          />
        )}
      </div>
      <button className="plan-link" onClick={() => void addToShortlist()} disabled={shortlisted}>
        {shortlisted ? '✓ On your shortlist' : `Add to shortlist as ${category}`}
      </button>
    </div>
  );
}

function Shortlist({ plan, setup }: { plan: Plan; setup: SetupEntry[] }) {
  return (
    <div className="empty-state">
      <strong>
        {setup.length} of {plan.parts.length} parts shortlisted
      </strong>
      {plan.parts.map((part) => {
        const added = setup.find((entry) => entry.category === part.category)?.product;
        return (
          <p key={part.category}>
            {part.category}:{' '}
            {added ? (
              <a href={added.url} target="_blank" rel="noreferrer">
                {added.title} · ${added.price.toFixed(2)}
              </a>
            ) : (
              <a href={part.search_url} target="_blank" rel="noreferrer">
                shop on Amazon (up to ${part.max_price.toFixed(0)})
              </a>
            )}
          </p>
        );
      })}
    </div>
  );
}

function App() {
  const [page, setPage] = useState<PageState>({ status: 'loading' });
  const [tab, setTab] = useState<'product' | 'shortlist'>('product');
  const [editing, setEditing] = useState(false);
  const plan = useStoredItem(planItem);
  const setup = useStoredItem(setupItem) ?? [];

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
  const total = setup.reduce((sum, entry) => sum + entry.product.price, 0);
  // What adding this product would add to the total
  const onShortlist = setup.some((entry) => entry.product.asin === product?.asin);
  const change = product && !onShortlist ? product.price : 0;

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
          <button className="icon-button" aria-label="Close" onClick={() => window.close()}>
            ×
          </button>
        </div>
      </header>

      <section className="project-bar">
        <div className="project-heading">
          <h2>{plan?.transcript ?? 'New project'}</h2>
          <div className="project-actions">
            <span className="save-status">
              <span className="status-dot">!</span>
              Not saved
            </span>
            <button aria-label="Edit project" onClick={() => setEditing(true)}>
              ✎
            </button>
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
            Shortlist · {setup.length}
          </button>
        </div>
      </section>

      <section className="content">
        <div className="section-heading">
          <span className="section-icon">☷</span>
          <h2>CTO</h2>
        </div>

        {plan === null || editing ? (
          <RequestForm initialText={plan?.transcript ?? ''} onDone={() => setEditing(false)} />
        ) : !plan ? null : tab === 'shortlist' ? (
          <Shortlist plan={plan} setup={setup} />
        ) : product ? (
          <ProductFit key={product.asin} product={product} plan={plan} setup={setup} />
        ) : (
          <div className="empty-state">
            <strong>No product open</strong>
            <p>Open an Amazon product page to evaluate the item you are viewing.</p>
          </div>
        )}
      </section>

      {plan && (
        <footer className="summary">
          <div className="summary-card">
            <div className="summary-line">
              <span>Setup total</span>
              <strong>${total.toFixed(2)}</strong>
            </div>
            <p>
              {setup.length} of {plan.parts.length} parts on your shortlist
            </p>
            <hr />
            <div className="summary-line summary-detail">
              <span>Budget remaining</span>
              <strong>${(plan.budget - total).toFixed(2)}</strong>
            </div>
            {product && (
              <div className="summary-line summary-detail">
                <span>Change from current</span>
                <span>+${change.toFixed(2)}</span>
              </div>
            )}
          </div>
          <button className="plan-link" onClick={() => setTab('shortlist')}>
            Open project plan <span>→</span>
          </button>
        </footer>
      )}
    </main>
  );
}

export default App;
