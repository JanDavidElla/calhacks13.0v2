import { useState, type FormEvent } from 'react';
import { createPlan } from '@/utils/api';
import { planItem, setupItem } from '@/utils/storage';

type RequestFormProps = {
  initialText: string;
  onDone: () => void;
};

function RequestForm({ initialText, onDone }: RequestFormProps) {
  const [text, setText] = useState(initialText);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const plan = await createPlan(text.trim());
      // A new plan starts a new setup
      await setupItem.setValue([]);
      await planItem.setValue(plan);
      onDone();
    } catch (caught) {
      // A too-broad request comes back as a question, so keep the box for a clearer one
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="request-form" onSubmit={handleSubmit}>
      <label htmlFor="request">What are you shopping for?</label>
      <textarea
        id="request"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="A gaming PC for $600"
        rows={3}
        disabled={loading}
      />
      <button className="primary-button" type="submit" disabled={loading || !text.trim()}>
        {loading ? 'Planning…' : 'Make a checklist'}
      </button>
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default RequestForm;
