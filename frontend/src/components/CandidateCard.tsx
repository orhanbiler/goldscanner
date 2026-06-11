import { ArrowUpCircle, ExternalLink, EyeOff, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Item } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  item: Item;
  onSetStatus: (id: string, status: string) => void;
  /** When true, the item was rejected by the AI — show promote actions instead. */
  rejected?: boolean;
  onPromote?: (id: string, status: string) => void;
}

export function CandidateCard({ item, onSetStatus, rejected, onPromote }: Props) {
  const scored = item.confidence != null;
  const conf = Math.round((item.confidence ?? 0) * 100);
  const fav = item.status === "favorite";
  const confTone =
    conf >= 80 ? "bg-success" : conf >= 60 ? "bg-primary" : "bg-muted-foreground";

  return (
    <Card className="flex flex-col overflow-hidden">
      <a href={item.url} target="_blank" rel="noopener noreferrer" className="block">
        {item.image_url ? (
          <img
            src={item.image_url}
            alt=""
            loading="lazy"
            className="aspect-square w-full bg-muted object-cover"
          />
        ) : (
          <div className="flex aspect-square w-full items-center justify-center bg-muted text-muted-foreground">
            no image
          </div>
        )}
      </a>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-sm font-semibold leading-snug hover:underline"
        >
          {item.title}
        </a>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>
            Price{" "}
            <span className="font-semibold text-foreground">
              {item.price != null ? `$${item.price}` : "—"}
            </span>
          </span>
          <span>
            Bids{" "}
            <span className="font-semibold text-foreground">
              {item.num_bids ?? 0}
            </span>
          </span>
          {item.end_time && <span>Ends {item.end_time}</span>}
        </div>

        {scored ? (
          <div className="flex items-center gap-2">
            <span className="w-9 text-xs font-semibold tabular-nums text-muted-foreground">
              {conf}%
            </span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div className={cn("h-full", confTone)} style={{ width: `${conf}%` }} />
            </div>
          </div>
        ) : (
          rejected && (
            <Badge variant="secondary" className="self-start">
              Skipped by title filter (not scored)
            </Badge>
          )
        )}

        {item.reasoning && (
          <p className="rounded-md bg-muted/60 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            {item.reasoning}
          </p>
        )}

        {rejected ? (
          <div className="mt-auto flex items-center gap-2 pt-1">
            <Button asChild size="sm" variant="outline" className="flex-1">
              <a href={item.url} target="_blank" rel="noopener noreferrer">
                View <ExternalLink />
              </a>
            </Button>
            <Button
              size="sm"
              className="flex-1"
              onClick={() => onPromote?.(item.item_id, "new")}
              title="The AI was wrong — move this to Candidates"
            >
              <ArrowUpCircle /> Candidate
            </Button>
            <Button
              size="sm"
              variant="success"
              onClick={() => onPromote?.(item.item_id, "favorite")}
              title="Move to Candidates and favorite it"
            >
              <Star />
            </Button>
          </div>
        ) : (
          <>
            <div className="mt-auto flex items-center gap-2 pt-1">
              <Button asChild size="sm" className="flex-1">
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  View <ExternalLink />
                </a>
              </Button>
              <Button
                size="sm"
                variant={fav ? "success" : "outline"}
                onClick={() => onSetStatus(item.item_id, fav ? "new" : "favorite")}
                title={fav ? "Saved — tap to unsave" : "Favorite"}
              >
                <Star className={fav ? "fill-current" : ""} />
              </Button>
              {!fav && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onSetStatus(item.item_id, "dismissed")}
                  title="Hide (and teach the AI this is not a match)"
                >
                  <EyeOff />
                </Button>
              )}
            </div>

            {fav && (
              <Badge variant="success" className="self-start">
                ★ Favorited
              </Badge>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
