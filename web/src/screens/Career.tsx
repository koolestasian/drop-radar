import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, query, type CareerInput, type CareerPage, type CareerRecord } from "../api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, ListSkeleton } from "../components/common";

const EMPTY: CareerInput = { kind: "fact", label: "", text: "", context: "", source_note: "", state: "draft", fact_refs: [] };
const select = "min-h-11 w-full rounded-lg border border-input bg-card px-3 text-base focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

function History({ id }: { id: string }) {
  const history = useInfiniteQuery({
    queryKey: ["career", "history", id], initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => api<CareerRecord[]>(`/api/career/${encodeURIComponent(id)}/history${query({ before: pageParam, limit: 20 })}`),
    getNextPageParam: (page) => page.length === 20 ? page[page.length - 1].revision : undefined,
  });
  return <div className="mt-4 border-t border-border pt-4">
    <h3 className="font-semibold">Revision history</h3>
    {history.isPending && <ListSkeleton rows={1} label="Loading revision history" />}
    {history.isError && <ErrorNote error={history.error} retry={() => void history.refetch()} />}
    <ol className="mt-3 flex flex-col gap-3">
      {history.data?.pages.flat().map((r) => <li key={r.revision} className="rounded-lg bg-muted p-3 text-sm">
        <p className="font-medium">Revision {r.revision} · {r.state}</p>
        <p className="mt-1 whitespace-pre-wrap break-words">{r.text}</p>
        <p className="mt-1 break-words text-muted-foreground">Source: {r.source_note || "Not recorded"}</p>
        {r.context && <p className="mt-1 break-words">Context: {r.context}</p>}
      </li>)}
    </ol>
    {history.hasNextPage && <Button variant="outline" className="mt-3 min-h-11" disabled={history.isFetchingNextPage}
      onClick={() => void history.fetchNextPage()}>Older revisions</Button>}
  </div>;
}

function Editor({ initial, facts, close, saved }: {
  initial: CareerRecord | null; facts: CareerRecord[]; close: () => void; saved: () => void;
}) {
  const qc = useQueryClient();
  const label = useRef<HTMLInputElement>(null);
  const [body, setBody] = useState<CareerInput>(() => initial ? {
    kind: initial.kind, label: initial.label, text: initial.text, context: initial.context,
    source_note: initial.source_note, state: "draft", fact_refs: initial.fact_refs,
  } : { ...EMPTY });
  useEffect(() => { label.current?.focus(); }, []);
  const save = useMutation({
    mutationFn: () => api<CareerRecord>(initial ? `/api/career/${encodeURIComponent(initial.id)}` : "/api/career", {
      method: initial ? "PUT" : "POST", body: JSON.stringify(initial ? { ...body, expected_revision: initial.revision } : body),
    }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["career"] }); saved(); },
  });
  const field = (name: keyof CareerInput, value: unknown) => setBody((b) => ({ ...b, [name]: value }));
  const validFacts = facts.filter((f) => f.kind === "fact" && f.reusable);
  return <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}
    aria-label="Career record" className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5">
    <h2 className="text-lg font-semibold">{initial ? "Revise record" : "Add a career record"}</h2>
    {initial && <p className="text-sm text-muted-foreground">Editing revision {initial.revision}. Changes start as a draft; select Approved after reviewing them.</p>}
    <fieldset disabled={save.isPending} className="flex min-w-0 flex-col gap-4">
      <label className="flex flex-col gap-1.5 text-sm font-medium">Record type
        <select value={body.kind} className={select} disabled={Boolean(initial)}
          onChange={(e) => setBody((b) => ({ ...b, kind: e.target.value as CareerInput["kind"], fact_refs: [], context: "" }))}>
          <option value="fact">Career fact</option><option value="answer">Reusable answer</option>
        </select>
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">{body.kind === "fact" ? "Fact label" : "Question or answer label"}
        <Input ref={label} value={body.label} required maxLength={200} className="min-h-11 text-base"
          onChange={(e) => field("label", e.target.value)} />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">{body.kind === "fact" ? "Fact" : "Answer"}
        <Textarea value={body.text} required maxLength={10000} rows={4} onChange={(e) => field("text", e.target.value)} />
      </label>
      {body.kind === "answer" && <>
        <label className="flex flex-col gap-1.5 text-sm font-medium">Where this answer applies
          <Textarea value={body.context} required maxLength={2000} rows={2} placeholder="Question meaning and any company, role or eligibility limits"
            onChange={(e) => field("context", e.target.value)} />
        </label>
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="text-sm font-medium">Supporting approved facts</legend>
          <p className="text-sm text-muted-foreground">Only loaded, current approved facts are selectable. A changed fact requires a fresh review.</p>
          {validFacts.map((f) => <label key={f.id} className="flex min-h-11 items-center gap-3 rounded-lg border border-border p-3 text-sm">
            <input type="checkbox" className="size-5 shrink-0" checked={body.fact_refs?.some((ref) => ref.id === f.id) ?? false}
              onChange={(e) => field("fact_refs", e.target.checked
                ? [...(body.fact_refs ?? []).filter((ref) => ref.id !== f.id), { id: f.id, revision: f.revision }]
                : (body.fact_refs ?? []).filter((ref) => ref.id !== f.id))} />
            <span className="break-words">{f.label} · revision {f.revision}</span>
          </label>)}
          {!validFacts.length && <p className="text-sm text-muted-foreground">Add and approve supporting facts first, or record your own confirmation below.</p>}
          {body.fact_refs?.map((ref) => {
            const fact = validFacts.find((f) => f.id === ref.id && f.revision === ref.revision);
            return fact ? null : <div key={ref.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span>Supporting fact revision {ref.revision} needs review.</span>
              <Button type="button" variant="outline" className="min-h-11" onClick={() => field("fact_refs", body.fact_refs?.filter((r) => r.id !== ref.id))}>Remove outdated reference</Button>
            </div>;
          })}
        </fieldset>
      </>}
      <label className="flex flex-col gap-1.5 text-sm font-medium">Source or confirmation note
        <Textarea value={body.source_note} required={body.state === "approved"} maxLength={2000} rows={2}
          placeholder="Source document, project link, or what you personally confirmed"
          onChange={(e) => field("source_note", e.target.value)} />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">Review state
        <select className={select} value={body.state} onChange={(e) => field("state", e.target.value)}>
          <option value="draft">Draft</option><option value="approved">Approved by me</option><option value="retired">Retired</option>
        </select>
      </label>
      <p className="text-sm text-muted-foreground">Approval confirms your review. It does not independently verify a claim or authorize sending, applying or spending.</p>
    </fieldset>
    {save.isError && <ErrorNote error={save.error} />}
    {save.error instanceof ApiError && save.error.status === 409 && <p className="text-sm">Your edits remain here. Cancel to load the latest record before revising again.</p>}
    <div className="flex flex-wrap gap-3">
      <Button type="submit" className="min-h-11" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save record"}</Button>
      <Button type="button" variant="outline" className="min-h-11" disabled={save.isPending} onClick={() => { void qc.invalidateQueries({ queryKey: ["career"] }); close(); }}>Cancel</Button>
    </div>
  </form>;
}

export function Career() {
  const [editing, setEditing] = useState<CareerRecord | null | undefined>();
  const [history, setHistory] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const add = useRef<HTMLButtonElement>(null);
  const library = useInfiniteQuery({
    queryKey: ["career", "records"], initialPageParam: "",
    queryFn: ({ pageParam }) => api<CareerPage>(`/api/career${query({ after: pageParam, limit: 100 })}`),
    getNextPageParam: (page) => page.next_after ?? undefined,
  });
  const records = library.data?.pages.flatMap((p) => p.records) ?? [];
  const close = () => { setEditing(undefined); requestAnimationFrame(() => add.current?.focus()); };
  return <section className="flex flex-col gap-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-bold tracking-tight">Career evidence</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Your private facts and reusable answers. Preserve what is true, where it came from, and when you reviewed it.</p></div>
      <Button ref={add} className="min-h-11" disabled={editing !== undefined || library.isPending || library.isError}
        onClick={() => { setEditing(null); setNotice(""); }}>Add record</Button>
    </header>
    {notice && <p role="status" className="rounded-lg bg-muted p-3 text-sm">{notice}</p>}
    {library.isPending && <ListSkeleton rows={3} label="Loading career evidence" />}
    {library.isError && <ErrorNote error={library.error} retry={() => void library.refetch()} />}
    {editing !== undefined && <Editor key={editing?.id ?? "new"} initial={editing} facts={records} close={close}
      saved={() => { close(); setNotice("Career record saved. Revision history is preserved."); }} />}
    {!library.isPending && !library.isError && !records.length && editing === undefined && <div className="rounded-xl border border-border p-6">
      <h2 className="font-semibold">Start with one fact you can defend</h2>
      <p className="mt-2 text-sm text-muted-foreground">Add a project contribution, achievement, skill, education detail or experience. Reusable answers can cite approved facts.</p>
    </div>}
    <div className="grid min-w-0 gap-4 lg:grid-cols-2">
      {records.map((r) => <article key={r.id} className="min-w-0 rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center gap-2"><Badge variant="secondary">{r.kind === "fact" ? "Fact" : "Answer"}</Badge>
          <Badge variant="outline">{r.state === "approved" && !r.reusable ? "Needs review" : r.state}</Badge>
          <span className="text-xs text-muted-foreground">Revision {r.revision}</span></div>
        <h2 className="mt-3 break-words font-semibold">{r.label}</h2>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm">{r.text}</p>
        {r.context && <p className="mt-3 break-words text-sm"><strong>Applies to:</strong> {r.context}</p>}
        <p className="mt-3 break-words text-sm text-muted-foreground">Source: {r.source_note || "Not recorded"}</p>
        {r.state === "approved" && !r.reusable && <p className="mt-3 text-sm">Supporting facts changed or need approval. Review before reuse.</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" disabled={editing !== undefined}
            onClick={() => { setEditing(r); setNotice(""); }}>Revise {r.kind}</Button>
          <Button variant="ghost" className="min-h-11" aria-expanded={history === r.id}
            onClick={() => setHistory(history === r.id ? null : r.id)}>{history === r.id ? "Hide history" : "Show history"}</Button>
        </div>
        {history === r.id && <History id={r.id} />}
      </article>)}
    </div>
    {library.hasNextPage && <Button variant="outline" className="min-h-11 self-start" disabled={library.isFetchingNextPage}
      onClick={() => void library.fetchNextPage()}>Load more records</Button>}
  </section>;
}
