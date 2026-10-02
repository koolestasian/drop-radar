import { useEffect, useState } from "react";
import { useMutation, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { setStatus, type ActionStatus, type Opportunity, type Page } from "./api/client";

type Cached = Page | InfiniteData<Page> | undefined;

/** Apply `update` to this opportunity wherever it sits in any cached list. */
export function patchCachedOpportunity(qc: QueryClient, id: string, update: (o: Opportunity) => Opportunity) {
  const mapPage = (page: Page): Page => ({ ...page, items: page.items.map((o) => (o.id === id ? update(o) : o)) });
  qc.setQueriesData<Cached>({ queryKey: ["opportunities"] }, (data) => {
    if (!data) return data;
    if ("pages" in data) return { ...data, pages: data.pages.map(mapPage) };
    return mapPage(data);
  });
}

export function useSetStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, notes }: { id: string; status?: ActionStatus; notes?: string }) =>
      setStatus(id, { status, notes }),
    onMutate: async ({ id, status, notes }) => {
      await qc.cancelQueries({ queryKey: ["opportunities"] });
      const snapshot = qc.getQueriesData<Cached>({ queryKey: ["opportunities"] });
      patchCachedOpportunity(qc, id, (o) => ({
        ...o,
        action: { status: status ?? o.action?.status ?? "new", notes: notes ?? o.action?.notes ?? "" },
      }));
      return { snapshot };
    },
    onError: (_err, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) qc.setQueryData(key, data);
    },
    onSuccess: (saved) => patchCachedOpportunity(qc, saved.id, () => saved),
    onSettled: () => qc.invalidateQueries({ queryKey: ["opportunities", "board"] }),
  });
}

/** True while the media query matches (e.g. the desktop layout with a persistent detail pane). */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatches(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return matches;
}
