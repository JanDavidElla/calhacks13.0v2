import { useEffect, useRef, useState, type ReactNode } from 'react';
import planeLogo from '@/assets/default.png';
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
import { BearAvatar, BearOverlay, useBearPhase } from './Bear';
import CartStatus from './CartStatus';
import RequestForm from './RequestForm';
import { useAlternatives, type AlternativesState } from './useAlternatives';
import { useEvaluation, type EvaluationState } from './useEvaluation';
import { useOtherStores, type OtherStoresState } from './useOtherStores';
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

// "★ 4.6 · 1,845 ratings", or just the stars when Amazon gave no count
function ratingSummary(stars: number | null, count: number | null): string | null {
  if (stars === null) return null;
  const rating = `★ ${stars.toFixed(1)}`;
  if (count === null) return rating;
  return `${rating} · ${count.toLocaleString('en-US')} ${count === 1 ? 'rating' : 'ratings'}`;
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
          const rating = ratingSummary(product.stars, product.ratings_count);
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
              {rating && <span className="alternative-rating">{rating}</span>}
              {why && <span className="alternative-reason">{why.reason}</span>}
            </a>
          );
        })}
    </div>
  );
}

type OtherStoresProps = {
  product: Product;
  state: OtherStoresState;
};

// The cheapest exact match at another store, or nothing when no store has it
function OtherStores({ product, state }: OtherStoresProps) {
  if (state.status === 'loading') return <p className="page-hint">Checking other stores…</p>;
  // Usually Google blocking the search; a quiet note, since the score above still holds
  if (state.status === 'failed') return <p className="page-hint">Other stores didn&apos;t answer this time.</p>;
  const cheapest = state.status === 'done' ? state.offers[0] : undefined;
  if (!cheapest) return null;
  // In cents first, so $74.99 - $89.99 is exactly -15 and an equal price reads "same price"
  const difference = Math.round((cheapest.price - product.price) * 100) / 100;

  return (
    <a
      className={difference < 0 ? 'other-store other-store-cheaper' : 'other-store'}
      href={cheapest.url}
      target="_blank"
      rel="noreferrer"
    >
      <strong>Also at {cheapest.store}</strong>
      <span>
        ${cheapest.price.toFixed(2)} · {priceDifference(difference)}
      </span>
    </a>
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
  const otherStores = useOtherStores(product);
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
      <OtherStores product={product} state={otherStores} />
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
          <ul>
            {unfilled.map((part) => (
              <li key={part.category}>
                <a href={part.search_url} target="_blank" rel="noreferrer">
                  ${part.max_price.toFixed(0)} · {part.category} 
                </a>
              </li>
            ))}
          </ul>
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
  const bear = useBearPhase(evaluation);
  const avatarRef = useRef<HTMLImageElement>(null);
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
  const score = evaluation?.status === 'done' ? evaluation.evaluation.score : null;
  // Views with no score of their own get a set face: pleased with the shopper's own picks on the
  // list, and waiting when there's no product to look at
  const face =
    !plan || editing
      ? undefined
      : tab === 'shortlist'
        ? 'yup'
        : page.status === 'none'
          ? 'neutral'
          : undefined;
  const asking = plan === null || editing;

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <img className="brand-icon" src={planeLogo} alt="" />
          <h1>gomdori</h1>
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
        {/* The prompt page has nothing to switch between, so the tabs only appear once it's done */}
        {!asking && (
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
        )}
      </section>

      <section className="content">
        {asking ? (
          // Nothing is scored on this page, so the bear just introduces itself
          <div className="greeting">
            <BearAvatar score={null} />
            <h2>Hi, I&apos;m gomdori</h2>
          </div>
        ) : (
          // Hidden while the bear is in the middle of the panel, as if it left its place to think
          <div className={bear.phase ? 'section-heading section-heading-away' : 'section-heading'}>
            <BearAvatar ref={avatarRef} score={score} face={face} />
            <h2>gomdori</h2>
          </div>
        )}

        {asking ? (
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
            {plan.budget_estimated && (
              <p className="summary-note">
                You didn&apos;t give a budget, so gomdori guessed ${Math.round(plan.budget)}. Tap
                the pencil to set your own.
              </p>
            )}
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
      <BearOverlay phase={bear.phase} score={score} target={avatarRef} onLanded={bear.land} />
    </main>
  );
}

export default App;
