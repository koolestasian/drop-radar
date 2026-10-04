import { useEffect, useLayoutEffect, useState } from "react";
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
    onSuccess: (saved, variables) => {
      patchCachedOpportunity(qc, saved.id, () => saved);
      qc.invalidateQueries({ queryKey: ["profile-suggestions"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      if (variables.status === "ignored") window.dispatchEvent(new CustomEvent("radar:hide", { detail: saved }));
    },
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

export type Density = "comfortable" | "compact";
const DENSITY_KEY = "radar.density";

/** Remembered per browser; falls back to comfortable when storage is unavailable. */
export function useDensity(): [Density, (d: Density) => void] {
  const [density, setDensity] = useState<Density>(() => {
    try {
      return localStorage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable";
    } catch {
      return "comfortable";
    }
  });
  const set = (d: Density) => {
    setDensity(d);
    try {
      localStorage.setItem(DENSITY_KEY, d);
    } catch {
      /* session-only */
    }
  };
  return [density, set];
}

export type Theme = "light" | "dark" | "system";
const THEME_KEY = "radar.theme";
const themeValue = (value: string | null): Theme => value === "light" || value === "dark" ? value : "system";

export function useTheme(): [Theme, (theme: Theme) => void, boolean] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return themeValue(localStorage.getItem(THEME_KEY)); }
    catch { return "system"; }
  });
  const deviceDark = useMediaQuery("(prefers-color-scheme: dark)");
  const dark = theme === "dark" || (theme === "system" && deviceDark);
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')!.content = dark ? "#0b0f14" : "#f7f8fa";
  }, [dark]);
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null) setTheme(themeValue(event.newValue));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const set = (value: Theme) => {
    setTheme(value);
    try { localStorage.setItem(THEME_KEY, value); }
    catch { /* session-only */ }
  };
  return [theme, set, dark];
}
