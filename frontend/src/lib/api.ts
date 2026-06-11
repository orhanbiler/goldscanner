export interface Item {
  item_id: string;
  title: string;
  price: string | null;
  end_time: string | null;
  num_bids: number | null;
  image_url: string | null;
  url: string;
  matched: number;
  confidence: number | null;
  reasoning: string | null;
  status: string;
}

export interface Example {
  id: number;
  item_id: string | null;
  title: string | null;
  image_url: string;
  label: "positive" | "negative";
  note: string | null;
  created: number;
}

export interface Counts {
  seen: number;
  matched: number;
  rejected: number;
  new: number;
  favorite: number;
  dismissed: number;
}

export interface ExampleCounts {
  positive: number;
  negative: number;
  total: number;
}

export interface Status {
  counts: Counts;
  examples: ExampleCounts;
  guidance: string;
  target_description: string;
  last_scan_at: number | null;
  last_scan_matches: number;
  scanning: boolean;
  interval_seconds: number;
  use_ai: boolean;
  queries: string[];
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  status: () => fetch("/api/status").then(j<Status>),
  items: (status: string) =>
    fetch(`/api/items?status=${encodeURIComponent(status)}`).then(
      j<{ items: Item[]; counts: Counts }>,
    ),
  setStatus: (id: string, status: string) =>
    fetch(`/api/items/${encodeURIComponent(id)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }).then(j<{ ok: boolean; counts: Counts }>),
  promote: (id: string, status: string = "new") =>
    fetch(`/api/items/${encodeURIComponent(id)}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }).then(j<{ ok: boolean; counts: Counts }>),
  scan: () => fetch("/api/scan", { method: "POST" }),
  queue: (limit = 40) =>
    fetch(`/api/queue?limit=${limit}`).then(j<{ items: Item[] }>),
  examples: (label?: string) =>
    fetch(`/api/examples${label ? `?label=${label}` : ""}`).then(
      j<{ examples: Example[]; counts: ExampleCounts }>,
    ),
  addExample: (body: {
    image_url: string;
    label: "positive" | "negative";
    item_id?: string | null;
    title?: string | null;
    note?: string | null;
  }) =>
    fetch("/api/examples", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<{ ok: boolean; example: Example; counts: ExampleCounts }>),
  deleteExample: (id: number) =>
    fetch(`/api/examples/${id}`, { method: "DELETE" }).then(
      j<{ ok: boolean; counts: ExampleCounts }>,
    ),
  getGuidance: () => fetch("/api/guidance").then(j<{ text: string }>),
  setGuidance: (text: string) =>
    fetch("/api/guidance", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then(j<{ ok: boolean; text: string }>),
};
