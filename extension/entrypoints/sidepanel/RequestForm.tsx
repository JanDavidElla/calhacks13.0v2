import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, createPlan } from '@/utils/api';
import { planItem, setupItem } from '@/utils/storage';

type RequestFormProps = {
  initialText: string;
  onDone: () => void;
};

// The request the server answered with a question, kept so a short answer like "$800" builds on it
type Asked = {
  request: string;
  question: string;
};

function RequestForm({ initialText, onDone }: RequestFormProps) {
  const [text, setText] = useState(initialText);
  const [asked, setAsked] = useState<Asked | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (asked) textareaRef.current?.focus();
  }, [asked]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // An answer joins the request it answers, e.g. "A gaming PC, $800"
    const request = asked ? `${asked.request}, ${text.trim()}` : text.trim();
    setLoading(true);
    setError(null);
    try {
      const plan = await createPlan(request);
      // A new plan starts a new setup
      await setupItem.setValue([]);
      await planItem.setValue(plan);
      onDone();
    } catch (caught) {
      // A 400 is a question about the request, or why it can't be planned, so the box clears for
      // the answer. Other failures keep the text to send again.
      if (caught instanceof ApiError && caught.status === 400) {
        setAsked({ request, question: caught.message });
        setText('');
      } else {
        setError((caught as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }

  function changeRequest() {
    setText(asked?.request ?? '');
    setAsked(null);
    setError(null);
  }

  return (
    <form className="request-form" onSubmit={handleSubmit}>
      {asked && (
        <p className="request-context">
          You asked for “{asked.request}”.{' '}
          <button className="link-button" type="button" onClick={changeRequest} disabled={loading}>
            Change request
          </button>
        </p>
      )}
      <label htmlFor="request">{asked ? asked.question : 'What are you shopping for?'}</label>
      <textarea
        id="request"
        ref={textareaRef}
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={asked ? 'Your answer' : 'A gaming PC for $600'}
        rows={3}
        disabled={loading}
      />
      <button className="primary-button" type="submit" disabled={loading || !text.trim()}>
        {loading ? 'Planning…' : asked ? 'Answer' : 'Make a checklist'}
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
