import type { TranscriptLine } from "../store/callStore";

interface Props {
  finals: TranscriptLine[];
  partial: string | null;
}

const SPEAKER_LABEL: Record<TranscriptLine["speaker"], string> = {
  CALLER: "Caller",
  AI: "AI",
  OPERATOR: "Operator",
};

/**
 * Live transcript: finalized turns stack top-to-bottom; the in-flight partial
 * (the word-by-word ASR hypothesis) shows as a dimmed, italic line at the foot
 * that gets replaced as it grows and cleared when its final lands.
 */
export function Transcript({ finals, partial }: Props) {
  const empty = finals.length === 0 && !partial;
  return (
    <div
      data-testid="transcript"
      className="max-h-48 space-y-1.5 overflow-y-auto rounded bg-neutral-950/60 p-3 text-sm"
    >
      {empty && (
        <p className="text-neutral-600">Listening for the caller…</p>
      )}
      {finals.map((line) => (
        <p key={line.seq} className="leading-snug">
          <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
            {SPEAKER_LABEL[line.speaker]}
          </span>
          <span className="text-neutral-200">{line.text}</span>
        </p>
      ))}
      {partial && (
        <p data-testid="transcript-partial" className="leading-snug">
          <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
            Caller
          </span>
          <span className="italic text-neutral-500">{partial}…</span>
        </p>
      )}
    </div>
  );
}
