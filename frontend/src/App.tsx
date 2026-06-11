import { useCallback, useEffect, useState } from "react";
import { Loader2, Moon, RefreshCw, Sun } from "lucide-react";
import { toast } from "sonner";

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
      </header>

      <main className="container py-5">
        <Tabs defaultValue="candidates">
          <TabsList>
            <TabsTrigger value="candidates">Candidates</TabsTrigger>
            <TabsTrigger value="train">Train the AI</TabsTrigger>
          </TabsList>

          <TabsContent value="candidates">
            <CandidatesView counts={counts} onChanged={loadStatus} />
          </TabsContent>

          <TabsContent value="train">
            <TrainView onChanged={loadStatus} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
