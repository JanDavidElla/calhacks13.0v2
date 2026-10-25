import { useEffect, useState, type ReactNode } from 'react';
import type { Check, Plan, SetupEntry } from '@/utils/api';
import { GET_PRODUCT, PRODUCT_FOUND, type Product, type ProductFoundMessage } from '@/utils/page';
import { guessCategory } from '@/utils/category';
import {
  addToShortlist,
  cartCountItem,
  planItem,
  removeFromShortlist,
  saveScore,
  setupItem,
  type ShortlistEntry,
} from '@/utils/storage';
import { BearAvatar, BearOverlay } from './Bear';
import CartStatus from './CartStatus';
import RequestForm from './RequestForm';
import { useAlternatives, type AlternativesState } from './useAlternatives';
import { useEvaluation, type EvaluationState } from './useEvaluation';
import { useShortlistScores, type ShortlistScores } from './useShortlistScores';
import { useStoredItem } from './useStoredItem';

type PageState =
  | { status: 'loading' }
  | { status: 'none' }
  | { status: 'product'; product: Product };

type DisclosureTone = 'good' | 'bad' | 'warn';

type DisclosureProps = {
  title: string;
  checks: Check[];
  tone: DisclosureTone;
  startOpen?: boolean;
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

function Disclosure({ title, checks, tone, startOpen = true }: DisclosureProps) {
  const [open, setOpen] = useState(startOpen);

  return (
    <div className={`disclosure disclosure-${tone}`}>
      <button
        className="disclosure-heading"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className={`chevron ${open ? '' : 'chevron-closed'}`} aria-hidden="true">
         ⌄
        </span>
      </button>
      {open && (
        <ul className="disclosure-detail">
          {checks.map((check, index) => (
            <li key={index}>{check.reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function scoreLabel(score: number): string {
  if (score >= 80) return 'Great fit';
  if (score >= 50) return 'Conditional fit';
  return 'Poor fit';
}

type ScoreCardProps = {
  product: Product;
  state: EvaluationState;
};

function ScoreCard({ product, state }: ScoreCardProps) {
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
    </div>
  );
}

function priceDifference(difference: number | null): string {
  if (difference === null || difference === 0) return 'same price';
  const amount = `$${Math.abs(difference).toFixed(2)}`;
  return difference < 0 ? `${amount} less` : `${amount} more`;
}

function Alternatives({ state }: { state: AlternativesState }) {
  if (state.status === 'idle') return null;

  return (
    <div className="alternatives">
      <strong>Better options</strong>
      {state.status === 'loading' && (
        <p className="page-hint">Searching Amazon for a better fit. This takes about 30 seconds.</p>
      )}
      {state.status === 'error' && <p className="error-message">{state.message}</p>}
      {state.status === 'done' && state.alternatives.length === 0 && (
        <p className="page-hint">This is already the best fit we found.</p>
      )}
      {state.status === 'done' &&
        state.alternatives.map(({ product, score, checks, price_difference }) => {
          // Why it fits: against the setup when there is one, otherwise against the request
          const why =
            checks.find((check) => check.kind === 'compatibility') ??
            checks.find((check) => check.kind === 'match');
          return (
            <a
              key={product.asin}
              className="alternative"
              href={product.url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="alternative-heading">
                <strong>{score}%</strong>
                <span>
                  ${product.price.toFixed(2)} · {priceDifference(price_difference)}
                </span>
              </span>
              <span className="alternative-title">{product.title}</span>
              {why && <span className="alternative-reason">{why.reason}</span>}
            </a>
          );
        })}
    </div>
  );
}

type ProductFitProps = {
  product: Product;
  plan: Plan;
  setup: SetupEntry[];
  onEvaluation: (state: EvaluationState | null) => void;
};

// Analyzes the product as soon as its page opens; the parent keys it by ASIN
function ProductFit({ product, plan, setup, onEvaluation }: ProductFitProps) {
  const category = guessCategory(product.title, plan.parts);
  const part = plan.parts.find((candidate) => candidate.category === category) ?? plan.parts[0];
  const state = useEvaluation(product, plan.transcript, part, setup);
  // The bear lives outside the bubble, so it hears about the analysis from here
  useEffect(() => {
    onEvaluation(state);
    // Cleared when this closes, so the bear doesn't keep a verdict on a product that's gone
    return () => onEvaluation(null);
  }, [state, onEvaluation]);
  const score = state.status === 'done' ? state.evaluation.score : null;
  const alternatives = useAlternatives(product, plan.transcript, part, setup, score);
  // Remembered, so the product keeps this score on the list after it's added to the cart
  useEffect(() => {
    if (score !== null) void saveScore(product.asin, score);
  }, [product.asin, score]);
  const checks = state.status === 'done' ? state.evaluation.checks : [];
  const pros = checks.filter((check) => check.status === 'pass');
  const cons = checks.filter((check) => check.status === 'fail');
  // A warning on match or compatibility means the listing doesn't confirm a spec. On budget
  // or reviews it means a little over budget or a middling rating, so it gets its own box
  const warnings = checks.filter((check) => check.status === 'warn');
  const missing = warnings.filter((check) => check.kind === 'match' || check.kind === 'compatibility');
  const worthChecking = warnings.filter((check) => !missing.includes(check));
  const shortlisted = setup.some((entry) => entry.product.asin === product.asin);

  return (
    <div className="fit-card">
      <ScoreCard product={product} state={state} />
      <div className="disclosures">
        {/* Pros start closed: problems matter more, and a shopper opens pros to learn why */}
        {pros.length > 0 && <Disclosure tone="good" title="Pros" checks={pros} startOpen={false} />}
        {cons.length > 0 && (
          <Disclosure
            tone="bad"
            title={`Cons · ${cons.length} ${cons.length === 1 ? 'issue' : 'issues'}`}
            checks={cons}
          />
        )}
        {missing.length > 0 && (
          <Disclosure
            tone="warn"
            title={`Missing spec · ${missing.length} unverified`}
            checks={missing}
          />
        )}
        {worthChecking.length > 0 && (
          <Disclosure tone="warn" title="Worth checking" checks={worthChecking} />
        )}
      </div>
      <Alternatives state={alternatives} />
      <button
        className="plan-link"
        onClick={() => void addToShortlist(category, product)}
        disabled={shortlisted}
      >
        {shortlisted ? '✓ On your shortlist' : `Add to shortlist as ${category}`}
      </button>
    </div>
  );
}

type ShortlistItemProps = {
  entry: ShortlistEntry;
  score: number | undefined;
  scoring: boolean;
};

function scoreText(score: number | undefined, scoring: boolean, price: number): string {
  if (score !== undefined) return `${Math.round(score / 10)}/10`;
  // Scoring failed, so the price is the most useful thing to show
  return scoring ? 'Rating…' : `$${price.toFixed(2)}`;
}

function ShortlistItem({ entry, score, scoring }: ShortlistItemProps) {
  const [open, setOpen] = useState(false);
  const { product } = entry;

  return (
    <li className={open ? 'shortlist-item shortlist-item-open' : 'shortlist-item'}>
      <div className="shortlist-item-heading">
        {/* Some pages have no main image; an empty square keeps the names lined up */}
        {product.image ? (
          <img className="shortlist-image" src={product.image} alt="" />
        ) : (
          <span className="shortlist-image" />
        )}
        <div className="shortlist-item-text">
          <strong>{product.title}</strong>
          <span className="shortlist-score">{scoreText(score, scoring, product.price)}</span>
        </div>
        <button
          className="shortlist-toggle"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label="View the details"
        >
          <span className={`chevron ${open ? 'chevron-open' : ''}`} aria-hidden="true">
            ⌄
          </span>
        </button>
        <button
          className="shortlist-remove"
          aria-label={`Remove ${product.title}`}
          onClick={() => void removeFromShortlist(product.asin)}
        >
          ×
        </button>
      </div>
      {open && (
        <div className="shortlist-details">
          <p>
            {entry.category} · ${product.price.toFixed(2)}
          </p>
          <a href={product.url} target="_blank" rel="noreferrer">
            View on Amazon ↗
          </a>
        </div>
      )}
    </li>
  );
}

// What the avatar says. Only the inside scrolls, so the bubble and its notch stay put.
function SpeechBubble({ children }: { children: ReactNode }) {
  return (
    <div className="bubble">
      <div className="bubble-scroll">{children}</div>
    </div>
  );
}

type ShortlistProps = {
  plan: Plan;
  setup: ShortlistEntry[];
  ratings: ShortlistScores;
};

function Shortlist({ plan, setup, ratings }: ShortlistProps) {
  const unfilled = plan.parts.filter(
    (part) => !setup.some((entry) => entry.category === part.category),
  );

  return (
    <>
      {setup.length === 0 ? (
        <p className="page-hint">Nothing on your list yet. Add a product from its page.</p>
      ) : (
        <ul className="shortlist-items">
          {setup.map((entry) => (
            <ShortlistItem
              key={entry.product.asin}
              entry={entry}
              score={ratings.scores[entry.product.asin]}
              scoring={ratings.scoring.has(entry.product.asin)}
            />
          ))}
        </ul>
      )}
      {unfilled.length > 0 && (
        <div className="shortlist-unfilled">
          <span>Still needed</span>
          {unfilled.map((part) => (
            <a key={part.category} href={part.search_url} target="_blank" rel="noreferrer">
              {part.category} · shop on Amazon (up to ${part.max_price.toFixed(0)})
            </a>
          ))}
        </div>
      )}
      <CartStatus setup={setup} />
    </>
  );
}

function App() {
  const [page, setPage] = useState<PageState>({ status: 'loading' });
  const [tab, setTab] = useState<'product' | 'shortlist'>('product');
  const [editing, setEditing] = useState(false);
  const [evaluation, setEvaluation] = useState<EvaluationState | null>(null);
  const plan = useStoredItem(planItem);
  const setup = useStoredItem(setupItem) ?? [];
  const cartCount = useStoredItem(cartCountItem) ?? 0;
  // Here, not in the list, so cart items are rated before the list is opened
  const ratings = useShortlistScores(plan, setup);

  useEffect(() => {
    // This panel's window: messages and tab events from other windows are ignored
    let windowId: number | undefined;
    void browser.windows.getCurrent().then((window) => (windowId = window.id));

    const refresh = async () => {
      const product = await readActiveTab();
      setPage(product ? { status: 'product', product } : { status: 'none' });
    };
    const isShownTab = (tab?: { active: boolean; windowId: number }) =>
      tab?.active === true && tab.windowId === windowId;
    // The content script sends the product as soon as it can read it, so the analysis starts
    // before the page has finished loading
    const onMessage = (
      message: Partial<ProductFoundMessage>,
      sender: { tab?: { active: boolean; windowId: number } },
    ) => {
      if (message.type === PRODUCT_FOUND && message.product && isShownTab(sender.tab)) {
        setPage({ status: 'product', product: message.product });
      }
    };
    const onUpdated = (
      _tabId: number,
      change: { status?: string },
      tab: { active: boolean; windowId: number },
    ) => {
      if (!isShownTab(tab)) return;
      // Drop the old product's score at once, instead of showing it for the new page
      if (change.status === 'loading') setPage({ status: 'loading' });
      // A fallback for pages whose content script didn't send anything, like non-product pages
      if (change.status === 'complete') void refresh();
    };

    void refresh();
    browser.runtime.onMessage.addListener(onMessage);
    browser.tabs.onActivated.addListener(refresh);
    browser.tabs.onUpdated.addListener(onUpdated);
    return () => {
      browser.runtime.onMessage.removeListener(onMessage);
      browser.tabs.onActivated.removeListener(refresh);
      browser.tabs.onUpdated.removeListener(onUpdated);
    };
  }, []);

  const product = page.status === 'product' ? page.product : null;
  const total = setup.reduce((sum, entry) => sum + entry.product.price, 0);
  // What adding this product would do to the total: it replaces whatever fills its part
  const onShortlist = setup.some((entry) => entry.product.asin === product?.asin);
  const category = product && plan ? guessCategory(product.title, plan.parts) : '';
  const replaced = setup.find((entry) => entry.category === category)?.product.price ?? 0;
  const change = product && !onShortlist ? product.price - replaced : 0;

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
            List ({cartCount} in Cart)
          </button>
        </div>
      </section>

      <section className="content">
        <div className="section-heading">
          <BearAvatar
            score={evaluation?.status === 'done' ? evaluation.evaluation.score : null}
            // The list is the shopper's own picks, so the bear approves of it
            cheering={tab === 'shortlist' && Boolean(plan) && !editing}
          />
          <h2>CTO</h2>
        </div>

        {plan === null || editing ? (
          <RequestForm initialText={plan?.transcript ?? ''} onDone={() => setEditing(false)} />
        ) : !plan ? null : (
          // Keyed by what it shows, so another tab or product starts scrolled to the top
          <SpeechBubble key={tab === 'shortlist' ? tab : (product?.asin ?? page.status)}>
            {tab === 'shortlist' ? (
              <Shortlist plan={plan} setup={setup} ratings={ratings} />
            ) : product ? (
              <ProductFit
                key={product.asin}
                product={product}
                plan={plan}
                setup={setup}
                onEvaluation={setEvaluation}
              />
            ) : page.status === 'loading' ? (
              <div className="empty-state">
                <strong>Reading the page…</strong>
              </div>
            ) : (
              <div className="empty-state">
                <strong>No product open</strong>
                <p>Open an Amazon product page to evaluate the item you are viewing.</p>
              </div>
            )}
          </SpeechBubble>
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
                <span>
                  {change < 0 ? '-' : '+'}${Math.abs(change).toFixed(2)}
                </span>
              </div>
            )}
          </div>
          <button className="plan-link" onClick={() => setTab('shortlist')}>
            Open project plan <span>→</span>
          </button>
        </footer>
      )}
      <BearOverlay state={evaluation} />
    </main>
  );
}

export default App;
