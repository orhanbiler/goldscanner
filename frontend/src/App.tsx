import { useCallback, useEffect, useState } from "react";
import { Loader2, Moon, RefreshCw, Sun } from "lucide-react";
import { toast } from "sonner";

import { ActivityView } from "@/components/ActivityView";
import { CandidatesView } from "@/components/CandidatesView";
import { TrainView } from "@/components/TrainView";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Status } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("gs-theme");
    if (saved) return saved === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("gs-theme", dark ? "dark" : "light");
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

function SourceDiagnostics({ status }: { status: Status }) {
  const stats = status.source_stats ?? {};
  const notes = status.source_notes ?? {};
  const names = Array.from(
    new Set(
      [
        ...(status.sources ?? []),
        ...Object.keys(stats),
        ...Object.keys(notes),
      ].map((n) => n.replace(" (scrape)", "")),
    ),
  );
  if (names.length === 0) return null;

  return (
    <div className="container flex flex-wrap gap-1.5 pb-2.5">
      {names.map((name) => {
        const stat = stats[name];
        const note = notes[name];
        const error = stat?.error ?? null;
        const ok = stat && stat.fetched > 0 && !error;
        const tone = ok
          ? "border-success/40 bg-success/10 text-success"
          : error || note
            ? "border-destructive/30 bg-destructive/10 text-destructive"
            : "border-border bg-muted text-muted-foreground";
        const label = stat
          ? error
            ? `${name}: ${error}`
            : `${name}: ${stat.fetched} fetched`
          : note
            ? `${name}: ${note}`
            : `${name}: waiting for first scan`;
        return (
          <span
            key={name}
            className={`max-w-full truncate rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${tone}`}
            title={label}
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}

export default function App() {
  const { dark, toggle } = useDarkMode();
  const [status, setStatus] = useState<Status | null>(null);
  const [scanning, setScanning] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.status());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 30000);
    return () => clearInterval(t);
  }, [loadStatus]);

  async function scanNow() {
    setScanning(true);
    try {
      const res = await api.scan();
      if (res.ok) {
        const d = await res.json();
        toast.success(`Scan done — ${d.matches} match(es)`);
      } else {
        toast.message("A scan is already running");
      }
    } catch {
      toast.error("Scan failed");
    } finally {
      setScanning(false);
      loadStatus();
    }
  }

  const counts = status?.counts ?? {
    seen: 0,
    matched: 0,
    rejected: 0,
    new: 0,
    favorite: 0,
    dismissed: 0,
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex items-center gap-3 py-3">
          <div className="flex items-center gap-2 text-lg font-extrabold tracking-tight">
            <span className="text-xl">🪙</span> goldscanner
          </div>
          <div className="flex-1" />
          <Button variant="ghost" size="icon" onClick={toggle} title="Toggle theme">
            {dark ? <Sun /> : <Moon />}
          </Button>
          <Button onClick={scanNow} disabled={scanning}>
            {scanning ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            <span className="hidden sm:inline">Scan now</span>
          </Button>
        </div>
        <div className="container -mt-1 pb-2 text-xs text-muted-foreground">
          {status ? (
            <>
              {counts.matched} candidate(s) · {counts.seen} listings checked · last
              scan {timeAgo(status.last_scan_at)} ·{" "}
              {status.use_ai ? "AI scoring on" : "keyword-only"} ·{" "}
              {status.examples.total} training example(s)
            </>
          ) : (
            "Loading…"
          )}
        </div>
        {status && <SourceDiagnostics status={status} />}
      </header>

      <main className="container py-5">
        <Tabs defaultValue="candidates">
          <TabsList>
            <TabsTrigger value="candidates">Candidates</TabsTrigger>
            <TabsTrigger value="train">Train the AI</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>

          <TabsContent value="candidates">
            <CandidatesView counts={counts} onChanged={loadStatus} />
          </TabsContent>

          <TabsContent value="train">
            <TrainView onChanged={loadStatus} />
          </TabsContent>

          <TabsContent value="activity">
            <ActivityView />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
