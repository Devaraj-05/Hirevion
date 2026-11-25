/**
 * Hirevion's mark: the candidate app's waveform emblem (five bars, the middle one dotted as the
 * "i" of AI) on a blue-to-violet tile, so both apps carry the same sign.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`grid size-8 shrink-0 place-items-center rounded-[10px] bg-[linear-gradient(135deg,var(--brand-from),var(--brand-to))] shadow-[var(--shadow-sm)] ${className ?? ""}`}
    >
      <svg viewBox="0 0 24 24" className="size-5" fill="#ffffff" role="presentation">
        <rect x={3} y={11} width={2.4} height={6} rx={1.2} />
        <rect x={6.9} y={8.5} width={2.4} height={11} rx={1.2} />
        <rect x={10.8} y={8} width={2.4} height={12} rx={1.2} />
        <circle cx={12} cy={4.8} r={1.6} />
        <rect x={14.7} y={8.5} width={2.4} height={11} rx={1.2} />
        <rect x={18.6} y={11} width={2.4} height={6} rx={1.2} />
      </svg>
    </span>
  );
}
