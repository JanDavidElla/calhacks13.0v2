import { useState } from 'react';
import { SYNC_CART } from '@/utils/page';
import { cartReportItem, type CartReport, type ShortlistEntry } from '@/utils/storage';
import { useStoredItem } from './useStoredItem';

type CartStatusProps = {
  setup: ShortlistEntry[];
};

function itemStatus(item: CartReport['items'][number], setup: ShortlistEntry[]): string {
  if (setup.some((entry) => entry.product.asin === item.asin)) return 'on your shortlist';
  if (item.title === null) return "couldn't read its product page";
  if (item.category === null) return "doesn't match a part in this project";
  return `fits ${item.category}, which is already filled`;
}

// The content script on an Amazon tab syncs, since it can read the cart as the signed-in user
async function requestSync(): Promise<string | null> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  try {
    if (tab?.id === undefined) throw new Error('No active tab');
    await browser.tabs.sendMessage(tab.id, SYNC_CART);
    return null;
  } catch {
    // No content script answered: not an Amazon page, or one opened before the extension loaded
    return 'Open an Amazon page (or reload it if it was already open), then sync.';
  }
}

function CartStatus({ setup }: CartStatusProps) {
  const report = useStoredItem(cartReportItem);
  const [syncing, setSyncing] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  async function syncNow() {
    setSyncing(true);
    setHint(await requestSync());
    setSyncing(false);
  }

  return (
    <div className="cart-status">
      <strong>Amazon cart</strong>
      {report ? (
        <p>Checked at {new Date(report.checkedAt).toLocaleTimeString()}</p>
      ) : (
        <p>Not checked yet.</p>
      )}
      {report?.error && <p className="error-message">{report.error}</p>}
      {report && !report.error && report.items.length === 0 && <p>Your cart is empty.</p>}
      {report?.items.map((item) => (
        <p key={item.asin}>
          {item.title ?? item.asin}: {itemStatus(item, setup)}
        </p>
      ))}
      {hint && <p className="error-message">{hint}</p>}
      <button className="plan-link" onClick={() => void syncNow()} disabled={syncing}>
        {syncing ? 'Syncing…' : 'Sync cart now'}
      </button>
    </div>
  );
}

export default CartStatus;
