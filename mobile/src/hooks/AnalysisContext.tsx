/**
 * One analysis, shared by the screens that take part in it.
 *
 * The preview screen starts an analysis, the progress screen watches it, and
 * the result screen reads what came back. Passing a full result through
 * navigation params would serialise it into the route state; holding it in one
 * provider above the navigator keeps a single instance of `useLabelAnalysis`
 * alive across the flow, which is what makes "uploaded once, re-checked
 * without re-uploading" true.
 */

import { createContext, useContext, type ReactNode } from 'react';

import { useLabelAnalysis, type LabelAnalysis } from './useLabelAnalysis';

const AnalysisContext = createContext<LabelAnalysis | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const analysis = useLabelAnalysis();
  return <AnalysisContext.Provider value={analysis}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis(): LabelAnalysis {
  const analysis = useContext(AnalysisContext);
  if (!analysis) {
    throw new Error('useAnalysis must be used inside an AnalysisProvider.');
  }
  return analysis;
}
