import { useMemo, useState } from "react";
import type { Annotation, Spectrum } from "./api";
import { FragmentIons } from "./FragmentIons";

interface SelectionState {
  context: string;
  chosen?: Set<string>;
  focused?: string;
}

/** Share fragment visibility and focus between the table, spectrum, and XIC. */
export function useFragmentSelection(
  context: string,
  spectrum: Spectrum | undefined,
  annotations: Annotation[]
) {
  const rows = useMemo(
    () => FragmentIons.rows(spectrum, annotations),
    [spectrum, annotations]
  );
  const [state, setState] = useState<SelectionState>({ context });
  const current = state.context === context ? state : { context };
  if (state.context !== context) setState(current);

  // An unset choice means Top 6. Keep explicit choices while annotations reload
  // for a tolerance edit, even when the intermediate annotation list is empty.
  const chosen = current.chosen || FragmentIons.top(rows);
  const selected = new Set(rows.filter((ion) => chosen.has(ion.id)).map((ion) => ion.id));
  const focused = rows.some((ion) => ion.id === current.focused)
    ? current.focused
    : undefined;

  /** Change visibility without changing annotation or extraction requests. */
  function toggle(id: string) {
    const chosen = new Set(selected);
    if (chosen.has(id)) chosen.delete(id);
    else chosen.add(id);
    setState({ ...current, chosen });
  }

  /** Toggle a shared highlight without selecting another spectrum or peptide. */
  function focus(id: string) {
    setState({ ...current, focused: current.focused === id ? undefined : id });
  }

  return {
    rows,
    selected,
    focused,
    toggle,
    focus,
    selectTop: () => setState({ ...current, chosen: FragmentIons.top(rows) }),
    selectAll: () => setState({ ...current, chosen: new Set(rows.map((ion) => ion.id)) }),
    clear: () => setState({ ...current, chosen: new Set() })
  };
}

export type FragmentSelection = ReturnType<typeof useFragmentSelection>;
