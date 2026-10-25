import { useEffect, useState } from 'react';
import defaultBear from '@/assets/default.png';
import epiphanyBear from '@/assets/epiphany.png';
import neutralBear from '@/assets/neutral.png';
import nopeBear from '@/assets/nope.png';
import thinkingBear from '@/assets/thinking.png';
import yupBear from '@/assets/yup.png';
import type { Evaluation } from '@/utils/api';
import type { EvaluationState } from './useEvaluation';

const EPIPHANY_MS = 1000;

type BearAvatarProps = {
  score: number | null;
  // Always the thumbs-up, whatever the score
  cheering?: boolean;
};

function avatarFor({ score, cheering }: BearAvatarProps): string {
  if (cheering) return yupBear;
  if (score === null) return defaultBear;
  if (score > 75) return yupBear;
  if (score > 45) return neutralBear;
  return nopeBear;
}

// The bear beside the speech bubble: its face is the verdict on the product
export function BearAvatar(props: BearAvatarProps) {
  return <img className="avatar" src={avatarFor(props)} alt="" />;
}

// Thinks over the panel while the product is analyzed, then has its epiphany for a moment
export function BearOverlay({ state }: { state: EvaluationState | null }) {
  const evaluation = state?.status === 'done' ? state.evaluation : null;
  // The result whose epiphany is over. Comparing results, not a flag, means the epiphany shows
  // on the very render the result arrives, with no frame of the panel in between
  const [finished, setFinished] = useState<Evaluation | null>(null);

  useEffect(() => {
    if (!evaluation) return;
    const timer = setTimeout(() => setFinished(evaluation), EPIPHANY_MS);
    return () => clearTimeout(timer);
  }, [evaluation]);

  const image =
    state?.status === 'loading'
      ? thinkingBear
      : evaluation && evaluation !== finished
        ? epiphanyBear
        : null;
  if (!image) return null;

  return (
    <div className="bear-overlay">
      <img src={image} alt="" />
    </div>
  );
}
