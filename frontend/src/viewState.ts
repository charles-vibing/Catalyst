/**
 * Two-view navigation state, synced to the query string.
 *
 * Deliberately not react-router. The dashboard has exactly two views and two
 * drill-down parameters, and the project's package.json is intentionally lean
 * (react + react-dom only) — a router would be more dependency than navigation.
 *
 * What the URL buys is demo-ability: the README already leans on deep links, and
 * "here is the SNF costing you $132k" needs to survive being pasted into an
 * email. Every exec drill-down state is addressable:
 *
 *   ?view=exec                        executive landing
 *   ?view=exec&facility=265001        drilled into one destination
 *   ?view=care&fin=007521             care-team view, patient selected
 */
import { useCallback, useEffect, useState } from "react";

export type ViewId = "exec" | "care";

/** Header line each view lifts into the shared shell header. */
export interface ViewMeta {
  as_of: string;
  as_of_mode: "frozen" | "live";
  org_name: string;
  summary: string;
}

export interface NavState {
  view: ViewId;
  facility: string | null;
  fin: string | null;
}

function parse(search: string): NavState {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  return {
    view: view === "care" ? "care" : "exec",
    facility: params.get("facility"),
    fin: params.get("fin"),
  };
}

function serialize(state: NavState): string {
  const params = new URLSearchParams();
  params.set("view", state.view);
  if (state.view === "exec" && state.facility) params.set("facility", state.facility);
  if (state.view === "care" && state.fin) params.set("fin", state.fin);
  return `?${params.toString()}`;
}

export function useNavState(): [NavState, (next: Partial<NavState>) => void] {
  const [state, setState] = useState<NavState>(() => parse(window.location.search));

  // Back / forward should move between views, not leave the page.
  useEffect(() => {
    const onPop = () => setState(parse(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: Partial<NavState>) => {
    setState((prev) => {
      const merged = { ...prev, ...next };
      const url = serialize(merged);
      if (url !== window.location.search) {
        window.history.pushState(null, "", url);
      }
      return merged;
    });
  }, []);

  return [state, navigate];
}
