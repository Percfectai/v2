type RewriteInput = {
  target: "summary" | "beginning" | "middle" | "ending" | "cover" | "page";
  title: string;
  genre: string;
  styleId: string;
  cast: string;
  current: string;
  context?: string;
  invent: boolean;
};

type InkInput = {
  kind: "cover" | "interior" | "small" | "rewrite";
  page: number;
  title: string;
  issueNumber?: number;
  styleId: string;
  beat: string;
  cast: string;
  note?: string;
  actSummary?: string;
  hasPrevPage?: boolean;
  refs?: string[];
  model?: "grok-imagine-image" | "grok-imagine-image-quality" | "grok-imagine-image-2.0";
};

type PlanInput = {
  title: string;
  genre: string;
  cast: string;
  summary: string;
  beginning: string;
  middle: string;
  ending: string;
};

const API = `${import.meta.env.BASE_URL}api`;

async function post<T>(path: string, data: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(data),
  });
  const body = (await res.json().catch(() => null)) as T | { ok?: false; error?: string } | null;
  if (body && typeof body === "object") return body as T;
  return { ok: false, error: `Request failed (${res.status})` } as T;
}

export function rewriteCopy({ data }: { data: RewriteInput }) {
  return post<{ ok: true; text: string; pages?: string[] } | { ok: false; error: string }>("/rewrite", data);
}

export function inkPage({ data }: { data: InkInput }) {
  return post<{ ok: true; url: string } | { ok: false; error: string }>("/ink", data);
}

export function planBeats({ data }: { data: PlanInput }) {
  return post<{ ok: true; beats: string[] } | { ok: false; error: string }>("/plan", data);
}
