import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { setStatus, type Opportunity } from "../api/client";
import { patchCachedOpportunity } from "../hooks";
import { ErrorNote } from "./common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/** Mounted once: every successful hide, including the keyboard shortcut, uses this optional follow-up. */
export function HideFeedback() {
  const qc = useQueryClient();
  const [job, setJob] = useState<Opportunity | null>(null);
  const [term, setTerm] = useState("");
  const opener = useRef<HTMLElement | null>(null);
  const save = useMutation({
    mutationFn: ({ id, term }: { id: string; term: string }) => setStatus(id, { hide_term: term }),
    onSuccess: (saved) => {
      patchCachedOpportunity(qc, saved.id, () => saved);
      qc.invalidateQueries({ queryKey: ["profile-suggestions"] });
      setJob(null);
    },
  });
  useEffect(() => {
    const onHide = (event: Event) => {
      opener.current = document.activeElement as HTMLElement;
      setJob((event as CustomEvent<Opportunity>).detail);
      setTerm("");
      save.reset();
    };
    window.addEventListener("radar:hide", onHide);
    return () => window.removeEventListener("radar:hide", onHide);
  }, [save.reset]);
  return (
    <Sheet open={job !== null} onOpenChange={(open) => { if (!open && !save.isPending) setJob(null); }}>
      <SheetContent showCloseButton={false} className="overflow-y-auto" onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (opener.current?.isConnected && opener.current !== document.body) opener.current.focus();
        if (document.activeElement === document.body) {
          const fallback = [...document.querySelectorAll<HTMLElement>('main button:not(:disabled), main a, nav[aria-label="Main"] a')].find((el) => el.getClientRects().length > 0);
          fallback?.focus();
        }
      }}>
        <SheetHeader>
          <SheetTitle>Job hidden</SheetTitle>
          <SheetDescription>You can find it in Tracker → Hidden. Feedback is optional.</SheetDescription>
        </SheetHeader>
        <form className="flex flex-col gap-4 px-4" onSubmit={(event) => {
          event.preventDefault();
          if (job) save.mutate({ id: job.id, term });
        }}>
          <p className="text-sm font-medium [overflow-wrap:anywhere]">{job?.title}</p>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-semibold">Which title word or phrase isn’t for you?</legend>
            <p id="hide-help" className="text-sm text-muted-foreground">After three similar hides in 30 days, Settings will suggest an exclusion for you to approve.</p>
            <Input aria-label="Title word or phrase" aria-describedby="hide-help" aria-invalid={save.isError}
              maxLength={80} value={term} onChange={(event) => setTerm(event.target.value)}
              placeholder="For example, sales" className="min-h-11" />
          </fieldset>
          {save.isError && <ErrorNote error={save.error} />}
          <Button type="submit" size="lg" disabled={save.isPending || !term.trim()}>{save.isPending ? "Saving…" : save.isError ? "Retry feedback" : "Save feedback"}</Button>
          <Button type="button" variant="outline" size="lg" disabled={save.isPending} onClick={() => setJob(null)}>Skip feedback</Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}
