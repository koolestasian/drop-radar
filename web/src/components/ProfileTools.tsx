import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LinkDiagnostic, type ProfileSuggestions } from "../api/client";
import { ErrorNote, ListSkeleton } from "./common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

export function ProfileTools() {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const suggestions = useQuery({ queryKey: ["profile-suggestions"], queryFn: () => api<ProfileSuggestions>("/api/profile/suggestions") });
  const decide = useMutation({
    mutationFn: (body: { term: string; decision: "apply" | "mute" | "restore" }) => api<ProfileSuggestions>("/api/profile/suggestions", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (data, body) => {
      qc.setQueryData(["profile-suggestions"], data);
      if (body.decision === "apply") {
        qc.invalidateQueries({ queryKey: ["config", "profile"] });
        qc.invalidateQueries({ queryKey: ["opportunities"] });
        qc.invalidateQueries({ queryKey: ["summary"] });
      }
    },
    onError: () => qc.invalidateQueries({ queryKey: ["profile-suggestions"] }),
  });
  const diagnose = useMutation({
    mutationFn: (url: string) => api<LinkDiagnostic>("/api/diagnostics/link", { method: "POST", body: JSON.stringify({ url }) }),
  });
  return (
    <>
      <section aria-labelledby="suggestions-title" className="flex flex-col gap-4">
        <h2 id="suggestions-title" className="text-xl font-semibold">Profile suggestions</h2>
        <p className="text-sm text-muted-foreground">Three similar hides in 30 days can suggest a title exclusion. Your profile changes only when you approve.</p>
        {suggestions.isPending ? <ListSkeleton rows={1} /> : suggestions.isError ? <ErrorNote error={suggestions.error} retry={() => suggestions.refetch()} /> : (
          <>
            {suggestions.data.suggestions.length === 0 && <p className="text-sm text-muted-foreground">No suggestions yet.</p>}
            {suggestions.data.suggestions.map((s) => (
              <div key={s.term} className="flex flex-col gap-3 rounded-lg border border-border p-4">
                <h3 className="font-semibold [overflow-wrap:anywhere]">Exclude “{s.term}” from titles?</h3>
                <p className="text-sm">You gave this reason for {s.support_count} hidden jobs.</p>
                <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">{s.supporting_titles.map((title, i) => <li key={i} className="[overflow-wrap:anywhere]">{title}</li>)}</ul>
                <p className="text-sm">This would remove {s.affected_count} currently visible For you jobs. Curated Stories keep their existing rules.</p>
                {s.examples.length > 0 && <ul aria-label="Affected job examples" className="flex list-disc flex-col gap-1 pl-5 text-sm">{s.examples.map((title, i) => <li key={i} className="[overflow-wrap:anywhere]">{title}</li>)}</ul>}
                <div className="flex flex-wrap gap-2">
                  <Button size="lg" disabled={decide.isPending} onClick={() => decide.mutate({ term: s.term, decision: "apply" })}>Add exclusion</Button>
                  <Button variant="outline" size="lg" disabled={decide.isPending} onClick={() => decide.mutate({ term: s.term, decision: "mute" })}>Dismiss suggestion</Button>
                </div>
              </div>
            ))}
            {suggestions.data.muted.length > 0 && <fieldset className="flex flex-col gap-2">
              <legend className="text-sm font-semibold">Dismissed suggestions</legend>
              {suggestions.data.muted.map((term) => <div key={term} className="flex items-center justify-between gap-3">
                <span className="min-w-0 text-sm [overflow-wrap:anywhere]">{term}</span>
                <Button variant="outline" size="lg" disabled={decide.isPending} onClick={() => decide.mutate({ term, decision: "restore" })}>Restore</Button>
              </div>)}
            </fieldset>}
          </>
        )}
        {decide.isError && <ErrorNote error={decide.error} />}
        {decide.isSuccess && <p role="status" className="text-sm">{decide.variables.decision === "apply" ? "Exclusion added to your profile." : decide.variables.decision === "mute" ? "Suggestion dismissed until you restore it." : "Suggestion restored."}</p>}
      </section>
      <section aria-labelledby="diagnostic-title" className="flex flex-col gap-4">
        <h2 id="diagnostic-title" className="text-xl font-semibold">Why didn’t I see this?</h2>
        <p id="diagnostic-help" className="text-sm text-muted-foreground">Paste a public job link to check today’s rules and recorded evidence. Previewing a link does not add the job or send an alert.</p>
        <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); diagnose.mutate(url); }}>
          <label className="flex flex-col gap-2 text-sm font-semibold">
            Job link
            <Input type="url" required maxLength={2048} value={url} onChange={(event) => { setUrl(event.target.value); diagnose.reset(); }}
              aria-describedby="diagnostic-help" aria-invalid={diagnose.isError} placeholder="https://…" className="min-h-11" />
          </label>
          <Button type="submit" size="lg" disabled={diagnose.isPending || !url.trim()}>{diagnose.isPending ? "Checking…" : "Check link"}</Button>
        </form>
        {diagnose.isError && <ErrorNote error={diagnose.error} retry={() => diagnose.mutate(url)} />}
        {diagnose.isPending && <p role="status" className="text-sm">Checking the posting…</p>}
        {diagnose.data && <div aria-live="polite" className="flex flex-col gap-3">
          <p className="text-sm font-medium">{diagnose.data.summary}</p>
          <ol className="flex flex-col gap-3">
            {diagnose.data.checks.map((check) => <li key={check.stage} className="flex flex-col gap-2 rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold capitalize">{check.stage}</h3><Badge variant="outline">{check.verdict === "unknown" ? "Inconclusive" : check.verdict === "blocked" ? "Blocked" : "Passes"}</Badge></div>
              <p className="text-sm">{check.explanation}</p>
              {Object.entries(check.facts ?? {}).filter(([, value]) => value).map(([key, value]) => <p key={key} className="text-sm text-muted-foreground [overflow-wrap:anywhere]">{key}: {value}</p>)}
            </li>)}
          </ol>
        </div>}
      </section>
    </>
  );
}
