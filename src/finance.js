// PAC share as displayed. A candidate who took any PAC money never shows
// "0%": a small share that rounds to zero reads "<1%" so the label can't
// contradict a PAC donor list. Uses raw dollars, never the rounded percent.
export const pacPctLabel = (f) => {
  if (!f || f.pacPct == null) return 'n/a';
  if (f.pacPct === 0 && (f.fromPacs || 0) > 0) return '<1%';
  return `${f.pacPct}%`;
};
