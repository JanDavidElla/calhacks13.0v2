import { useCallback, useEffect, useRef, useState, type Ref, type RefObject } from 'react';
import defaultBear from '@/assets/default.png';
import epiphanyBear from '@/assets/epiphany.png';
import neutralBear from '@/assets/neutral.png';
import nopeBear from '@/assets/nope.png';
import thinkingBear from '@/assets/thinking.png';
import yupBear from '@/assets/yup.png';
import type { Evaluation } from '@/utils/api';
import type { EvaluationState } from './useEvaluation';

const EPIPHANY_MS = 1000;
const FLIGHT_MS = 700;

export type BearPhase = 'thinking' | 'epiphany' | 'verdict' | 'flying';

type Progress = { evaluation: Evaluation; phase: 'verdict' | 'flying' | 'landed' };

// The phases that end on a timer, and what follows. The flight ends when its animation does
const TIMED: Partial<Record<BearPhase, { next: Progress['phase']; ms: number }>> = {
  epiphany: { next: 'verdict', ms: EPIPHANY_MS },
  // Just long enough to see the verdict before the bear flies off with it
  verdict: { next: 'flying', ms: 500 },
};

function phaseOf(state: EvaluationState | null, progress: Progress | null): BearPhase | null {
  if (state?.status === 'loading') return 'thinking';
  if (state?.status !== 'done') return null;
  // A result the routine hasn't started on yet: it's new, so it begins at the epiphany
  if (progress?.evaluation !== state.evaluation) return 'epiphany';
  return progress.phase === 'landed' ? null : progress.phase;
}

// For each result the bear thinks, has its epiphany, shows the verdict, then flies to its place
// beside the bubble. The phase is null once it has landed, or when there's nothing to analyze
export function useBearPhase(state: EvaluationState | null) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const phase = phaseOf(state, progress);
  const evaluation = state?.status === 'done' ? state.evaluation : null;

  useEffect(() => {
    const step = phase && TIMED[phase];
    if (!evaluation || !step) return;
    const timer = setTimeout(() => setProgress({ evaluation, phase: step.next }), step.ms);
    return () => clearTimeout(timer);
  }, [evaluation, phase]);

  // The same function every render, so a re-render mid-flight doesn't restart the animation
  const land = useCallback(
    () => setProgress((current) => current && { ...current, phase: 'landed' }),
    [],
  );

  return { phase, land };
}

const FACES = { yup: yupBear, neutral: neutralBear };

type Pose = {
  score: number | null;
  // A set face for a view with no score of its own, used whatever the score
  face?: keyof typeof FACES;
};

function avatarFor({ score, face }: Pose): string {
  if (face) return FACES[face];
  if (score === null) return defaultBear;
  if (score > 75) return yupBear;
  if (score > 45) return neutralBear;
  return nopeBear;
}

// The bear beside the speech bubble: its face is the verdict on the product
export function BearAvatar({ ref, ...pose }: Pose & { ref?: Ref<HTMLImageElement> }) {
  return <img ref={ref} className="avatar" src={avatarFor(pose)} alt="" />;
}

type BearOverlayProps = {
  phase: BearPhase | null;
  score: number | null;
  // The avatar it flies to after its epiphany
  target: RefObject<HTMLImageElement | null>;
  onLanded: () => void;
};

// The bear in the middle of the panel while it works the product out
export function BearOverlay({ phase, score, target, onLanded }: BearOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const bearRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const overlay = overlayRef.current;
    const bear = bearRef.current;
    const avatar = target.current;
    if (phase !== 'flying' || !overlay || !bear || !avatar) return;

    const from = bear.getBoundingClientRect();
    const to = avatar.getBoundingClientRect();
    const timing = { duration: FLIGHT_MS, easing: 'ease-in-out', fill: 'forwards' } as const;
    // Shrinks from its top-left corner (see style.css), so it ends exactly over the avatar
    const move = `translate(${to.left - from.left}px, ${to.top - from.top}px)`;
    const flight = bear.animate(
      [{ transform: 'none' }, { transform: `${move} scale(${to.width / from.width})` }],
      timing,
    );
    const fade = overlay.animate([{ backgroundColor: 'transparent' }], timing);
    flight.onfinish = onLanded;
    return () => {
      flight.cancel();
      fade.cancel();
    };
  }, [phase, target, onLanded]);

  if (!phase) return null;
  const image =
    phase === 'thinking' ? thinkingBear : phase === 'epiphany' ? epiphanyBear : avatarFor({ score });

  return (
    <div ref={overlayRef} className="bear-overlay">
      <img
        ref={bearRef}
        className={phase === 'epiphany' ? 'bear-bounce' : undefined}
        src={image}
        alt=""
      />
    </div>
  );
}
