import { useState } from "react";
import { Bell, Bookmark, List, LogIn, SlidersHorizontal, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "../hooks";

const STEPS = [
  { icon: Zap, title: "New drops come first", text: "A yellow card marked New was found in the last 3 hours. The earlier you apply, the better your odds." },
  { icon: SlidersHorizontal, title: "Tell it what you want", text: "Pick your roles and locations in Settings. Only matching postings reach your feed." },
  { icon: Bookmark, title: "Track what you do", text: "Save, apply and add notes on a role. The Board shows every role by status." },
  { icon: Bell, title: "Get a push on your phone", text: "Turn on alerts in Settings and a new match buzzes your phone within minutes." },
];

const GUEST_STEPS = [
  STEPS[0],
  { icon: List, title: "Browse everything", text: "All jobs lists every posting the radar has found, from tech to finance. Search it and filter it." },
  { icon: LogIn, title: "Sign in for more", text: "Your own feed and profile, saved roles with notes on a Board, and a phone push when a match appears." },
];

const key = (user: string) => `radar.welcomed.${user}`;
const seen = (user: string) => {
  try {
    return localStorage.getItem(key(user)) === "1";
  } catch {
    return false;
  }
};

/** A one-time explainer for a new user. Dismissal is remembered in this browser only. */
export function Welcome({ user, sources, guest = false }: { user: string; sources: number; guest?: boolean }) {
  const [open, setOpen] = useState(() => !seen(user));
  const wide = useMediaQuery("(min-width: 640px)");
  const close = () => {
    setOpen(false);
    try {
      localStorage.setItem(key(user), "1");
    } catch {
      /* private mode: it will show again next visit */
    }
  };
  const title = "Welcome to Drop Radar";
  const blurb = `It watches ${sources} career pages and community lists around the clock and shows new internships and new-grad roles the moment they appear.`;
  const body = (
    <div className="flex flex-col gap-5">
      <ul className="flex flex-col gap-4">
        {(guest ? GUEST_STEPS : STEPS).map(({ icon: Icon, title: t, text }) => (
          <li key={t} className="flex gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Icon aria-hidden className="size-4" />
            </span>
            <div>
              <p className="text-sm font-semibold">{t}</p>
              <p className="text-sm text-muted-foreground">{text}</p>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-2">
        <Button asChild size="lg" onClick={close}>
          <a href={guest ? "#/login" : "#/settings"}>{guest ? "Sign in" : "Set up my profile"}</a>
        </Button>
        <Button size="lg" variant="ghost" onClick={close}>
          {guest ? "Keep browsing as a guest" : "Start browsing"}
        </Button>
      </div>
    </div>
  );
  const onOpenChange = (o: boolean) => (o ? setOpen(true) : close());

  return wide ? (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="gap-0 overflow-y-auto px-5 sm:max-w-sm">
        <SheetHeader className="px-0">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{blurb}</SheetDescription>
        </SheetHeader>
        {body}
      </SheetContent>
    </Sheet>
  ) : (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className="max-h-[88dvh]">
        <DrawerHeader>
          <DrawerTitle>{title}</DrawerTitle>
          <DrawerDescription>{blurb}</DrawerDescription>
        </DrawerHeader>
        <div className="overflow-y-auto px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))]">{body}</div>
      </DrawerContent>
    </Drawer>
  );
}
