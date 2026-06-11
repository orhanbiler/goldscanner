import { useEffect, useState } from "react";
import { Check, GraduationCap, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, type Example, type Item } from "@/lib/api";

interface Props {
  onChanged: () => void;
}

export function TrainView({ onChanged }: Props) {
  const [queue, setQueue] = useState<Item[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [guidance, setGuidance] = useState("");
  const [savedGuidance, setSavedGuidance] = useState("");
  const [urlInput, setUrlInput] = useState("");

  async function refresh() {
    const [q, ex, g] = await Promise.all([
      api.queue(30),
      api.examples(),
      api.getGuidance(),
    ]);
    setQueue(q.items);
    setExamples(ex.examples);
    setGuidance(g.text);
    setSavedGuidance(g.text);
  }

  useEffect(() => {
    refresh().catch(() => {});
  }, []);

  async function label(item: Item, lbl: "positive" | "negative") {
    if (!item.image_url) return;
    try {
      await api.addExample({
        image_url: item.image_url,
        label: lbl,
        item_id: item.item_id,
        title: item.title,
      });
      setQueue((q) => q.filter((i) => i.item_id !== item.item_id));
      toast.success(lbl === "positive" ? "Labeled ✅ gold bangle" : "Labeled ❌ not a match");
      const ex = await api.examples();
      setExamples(ex.examples);
      onChanged();
    } catch {
      toast.error("Could not save label");
    }
  }

  async function addByUrl(lbl: "positive" | "negative") {
    const url = urlInput.trim();
    if (!url) return;
    try {
      await api.addExample({ image_url: url, label: lbl });
      setUrlInput("");
      toast.success("Reference added");
      const ex = await api.examples();
      setExamples(ex.examples);
      onChanged();
    } catch {
      toast.error("Could not add that image");
    }
  }

  async function remove(id: number) {
    try {
      await api.deleteExample(id);
      setExamples((e) => e.filter((x) => x.id !== id));
      onChanged();
    } catch {
      toast.error("Could not remove");
    }
  }

  async function saveGuidance() {
    try {
      await api.setGuidance(guidance);
      setSavedGuidance(guidance);
      toast.success("Guidance saved — the AI will use it on the next scan");
    } catch {
      toast.error("Could not save guidance");
    }
  }

  const positives = examples.filter((e) => e.label === "positive");
  const negatives = examples.filter((e) => e.label === "negative");

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader className="flex-row items-center gap-2 space-y-0">
          <GraduationCap className="size-5 text-primary" />
          <CardTitle>Teach the AI</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Label real listings as <b className="text-success">✅ gold bangle</b> or{" "}
          <b className="text-destructive">❌ not</b>. The app feeds a set of your
          labeled photos — plus the guidance below — into the vision model every time
          it scores a new item, so it learns your taste. (This isn't fine-tuning the
          model's weights; it's few-shot steering, and it works immediately.)
          <div className="mt-3 flex gap-2">
            <Badge variant="success">{positives.length} positive</Badge>
            <Badge variant="destructive">{negatives.length} negative</Badge>
          </div>
        </CardContent>
      </Card>

      {/* Guidance */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Guidance (in your words)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Textarea
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            rows={4}
            placeholder="e.g. I want antique/vintage gold-filled bangles with real vitreous enamel (champlevé or cloisonné). Avoid modern costume jewelry, painted/epoxy 'enamel', and anything marked gold-plated or base metal."
          />
          <div>
            <Button onClick={saveGuidance} disabled={guidance === savedGuidance}>
              <Save /> Save guidance
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Label queue */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Label queue
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {queue.length} item(s) to review
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {queue.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Nothing to label yet. Listings the scanner sees will show up here, and
              your favorites/hides become labels automatically. You can also paste an
              image URL below.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {queue.map((it) => (
                <div key={it.item_id} className="overflow-hidden rounded-lg border">
                  <a href={it.url} target="_blank" rel="noopener noreferrer">
                    <img
                      src={it.image_url ?? ""}
                      alt=""
                      loading="lazy"
                      className="aspect-square w-full bg-muted object-cover"
                    />
                  </a>
                  <p className="line-clamp-1 px-2 pt-1.5 text-xs text-muted-foreground">
                    {it.title}
                  </p>
                  <div className="flex gap-1 p-2">
                    <Button
                      size="sm"
                      variant="success"
                      className="flex-1"
                      onClick={() => label(it, "positive")}
                    >
                      <Check />
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      className="flex-1"
                      onClick={() => label(it, "negative")}
                    >
                      <X />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add by URL */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a reference by image URL</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Input
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="https://…/photo.jpg"
          />
          <div className="flex gap-2">
            <Button variant="success" onClick={() => addByUrl("positive")}>
              <Plus /> Add as ✅ match
            </Button>
            <Button variant="destructive" onClick={() => addByUrl("negative")}>
              <Plus /> Add as ❌ not
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Manage examples */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <ExampleGrid title="✅ Positive examples" items={positives} onRemove={remove} />
        <ExampleGrid title="❌ Negative examples" items={negatives} onRemove={remove} />
      </div>
    </div>
  );
}

function ExampleGrid({
  title,
  items,
  onRemove,
}: {
  title: string;
  items: Example[];
  onRemove: (id: number) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {title}{" "}
          <span className="font-normal text-muted-foreground">({items.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">None yet.</p>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {items.map((ex) => (
              <div key={ex.id} className="group relative overflow-hidden rounded-md border">
                <img
                  src={ex.image_url}
                  alt=""
                  loading="lazy"
                  className="aspect-square w-full bg-muted object-cover"
                />
                <button
                  onClick={() => onRemove(ex.id)}
                  className="absolute right-1 top-1 rounded-full bg-background/85 p-1 text-destructive opacity-0 shadow transition-opacity group-hover:opacity-100"
                  title="Remove"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
