import { useEffect, useRef, useState } from "react";
import { Activity, Pause, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, type ActivityEvent } from "@/lib/api";

const MAX_KEPT = 400;

const LEVEL_STYLES: Record<string, string> = {
  success: "text-success",
  warn: "text-destructive",
  muted: "text-muted-foreground",
  info: "text-foreground",
};

function clock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ActivityView() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [live, setLive] = useState(true);
  const afterRef = useRef(0);

  useEffect(() => {
    let active = true;

    async function poll() {
      if (!live) return;
      try {
        const d = await api.activity(afterRef.current);
        if (!active) return;
        if (d.events.length) {
          afterRef.current = d.events[d.events.length - 1].id;
          // Newest first; cap the list so it stays snappy.
          setEvents((prev) => [...d.events.reverse(), ...prev].slice(0, MAX_KEPT));
        }
      } catch {
        /* ignore transient errors */
      }
    }

    poll();
    const t = setInterval(poll, 2500);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [live]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Activity className="size-5 text-primary" />
        <h2 className="text-base font-semibold">Live activity</h2>
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <span
            className={`inline-block size-2 rounded-full ${
              live ? "animate-pulse bg-success" : "bg-muted-foreground"
            }`}
          />
          {live ? "watching" : "paused"}
        </span>
        <div className="flex-1" />
        <Button variant="outline" size="sm" onClick={() => setLive((v) => !v)}>
          {live ? <Pause /> : <Play />}
          {live ? "Pause" : "Resume"}
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        A plain-language, real-time feed of what the bot is doing — searching each
        site, examining listings, scoring photos, and saving matches. Newest at the
        top. This feed resets when the app restarts.
      </p>

      <Card className="max-h-[70vh] overflow-y-auto p-0">
        {events.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            Waiting for activity… hit “Scan now” to see it work in real time.
          </p>
        ) : (
          <ul className="divide-y divide-border/60">
            {events.map((e) => (
              <li key={e.id} className="flex gap-3 px-4 py-2 text-sm">
                <span className="shrink-0 pt-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                  {clock(e.ts)}
                </span>
                <span className={LEVEL_STYLES[e.level] ?? "text-foreground"}>
                  {e.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
