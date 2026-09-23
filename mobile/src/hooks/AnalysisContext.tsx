/**
 * One inspection, shared by the screens that take part in it.
 *
 * The scan screen composes the set of photographs and starts the analysis, the
 * progress screen watches it, and the result screen reads what came back.
 * Passing a full result through navigation params would serialise it into the
 * route state; holding it in one provider above the navigator keeps a single
 * instance of `useLabelAnalysis` alive across the flow, which is what makes
 * "uploaded once, re-checked without re-uploading" true.
 *
 * `useInspectionImages` lives here for the same reason and a sharper one. The
 * photographs the user has gathered must survive navigating to the progress
 * screen and back after a failed upload - someone who photographed four panels
 * on a bad connection must not have to photograph them again. Route params or
 * screen state would lose them at exactly that moment.
 *
 * Two hooks rather than one, because they answer different questions with
 * different lifetimes: **what the user has gathered** (`selection`) and **what
 * the server made of what was submitted** (`analysis`). Merging them would make
 * "clear the photographs" and "clear the result" the same action, and a retry
 * needs the first to survive the second.
 */

import { createContext, useContext, type ReactNode } from 'react';

import { useInspectionImages, type InspectionImages } from './useInspectionImages';
import { useLabelAnalysis, type LabelAnalysis } from './useLabelAnalysis';

export interface Inspection {
  /** The verdict and the reading, from the server. */
  analysis: LabelAnalysis;
  /** The photographs gathered on the device, before and after submission. */
  selection: InspectionImages;
  /** Discard both: a new inspection, with nothing of the last one beside it. */
  startOver: () => void;
}

const AnalysisContext = createContext<Inspection | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const analysis = useLabelAnalysis();
  const selection = useInspectionImages();

  const startOver = () => {
    analysis.reset();
    selection.clear();
  };

  return (
    <AnalysisContext.Provider value={{ analysis, selection, startOver }}>
      {children}
    </AnalysisContext.Provider>
  );
}

function useInspectionContext(): Inspection {
  const inspection = useContext(AnalysisContext);
  if (!inspection) {
    throw new Error('useAnalysis must be used inside an AnalysisProvider.');
  }
  return inspection;
}

/**
 * The server side of the current inspection.
 *
 * Unchanged in shape and name from before image sets, so every screen that
 * reads a verdict reads it the same way.
 */
export function useAnalysis(): LabelAnalysis {
  return useInspectionContext().analysis;
}

/** The photographs gathered for the current inspection. */
export function useInspectionSelection(): InspectionImages {
  return useInspectionContext().selection;
}

/** Discard the photographs and the result together, for a fresh inspection. */
export function useStartOver(): () => void {
  return useInspectionContext().startOver;
}
