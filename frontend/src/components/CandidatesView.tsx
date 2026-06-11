import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { toast } from "sonner";

import { CandidateCard } from "@/components/CandidateCard";
import { Tabs, TabsList, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { api, type Counts, type Item } from "@/lib/api";

const FILTERS = [
  { key: "new", label: "New" },
  { key: "favorite", label: "★ Favs" },
  { key: "all", label: "All" },
  { key: "rejected", label: "Rejected" },
] as const;

interface Props {
  counts: Counts;
  onChanged: () => void;
}

export function CandidatesView({ counts, onChanged }: Props) {
  const [filter, setFilter] = useState<string>("new");
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);

  async function load(f: string) {
    setLoading(true);
    try {
      const d = await api.items(f);
      setItems(d.items);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(filter);
  }, [filter]);

  async function setStatus(id: string, status: string) {
    try {
      await api.setStatus(id, status);
      toast.success(
        status === "favorite"
          ? "Saved to favorites ★"
          : status === "dismissed"
            ? "Hidden — taught the AI this isn't a match"
            : "Removed from favorites",
      );
      load(filter);
      onChanged();
    } catch {
      toast.error("Something went wrong");
    }
  }

  async function promote(id: string, status: string) {
    try {
      await api.promote(id, status);
      toast.success(
        status === "favorite"
          ? "Moved to candidates & favorited ★ (taught the AI)"
          : "Moved to candidates (taught the AI)",
      );
      load(filter);
      onChanged();
    } catch {
      toast.error("Something went wrong");
    }
  }

  const badge = (key: string) =>
    key === "new"
      ? counts.new
      : key === "favorite"
        ? counts.favorite
        : key === "rejected"
          ? counts.rejected
          : counts.matched;

  return (
    <Tabs value={filter} onValueChange={setFilter}>
      <TabsList className="grid h-auto w-full grid-cols-4">
        {FILTERS.map((f) => (
          <TabsTrigger key={f.key} value={f.key} className="px-2">
            {f.label}
            <span className="ml-1 rounded-full bg-background/60 px-1.5 text-xs tabular-nums">
              {badge(f.key)}
            </span>
          </TabsTrigger>
        ))}
      </TabsList>

      {FILTERS.map((f) => (
        <TabsContent key={f.key} value={f.key}>
          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="h-72 animate-pulse rounded-lg border bg-muted/50"
                />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState filter={filter} />
          ) : (
            <>
              {filter === "rejected" && (
                <p className="mb-3 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                  Everything the scanner examined but didn't surface — with the
                  AI's reasoning. If it got one wrong, promote it: that also
                  teaches the AI it's a match.
                </p>
              )}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((it) => (
                  <CandidateCard
                    key={it.item_id}
                    item={it}
                    onSetStatus={setStatus}
                    rejected={filter === "rejected"}
                    onPromote={promote}
                  />
                ))}
              </div>
            </>
          )}
        </TabsContent>
      ))}
    </Tabs>
  );
}

function EmptyState({ filter }: { filter: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-20 text-center text-muted-foreground">
      <Search className="size-10 opacity-40" />
      <p className="max-w-sm text-sm">
        {filter === "favorite"
          ? "No favorites yet. Tap ★ on a candidate to save it here."
          : filter === "rejected"
            ? "Nothing rejected yet — everything scanned so far either matched or hasn't been scanned."
            : "Nothing here yet. The scanner runs every few minutes — check back soon, or hit “Scan now”."}
      </p>
    </div>
  );
}
