import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { STYLES, styleById, type StyleId } from "@/lib/comics/catalog";
import { GENRES } from "@/lib/comics/catalog";
import { castSheet, inkPage, planBeats, rewriteCopy, unlockIssue } from "@/lib/comics/ai.functions";
import { ChatRail } from "@/lib/comics/ChatRail";
import { helpText, type ChatVerb } from "@/lib/comics/chat-verbs";
import { fallbackBeat } from "@/lib/comics/ink-prompt";
import {
  newIssue,
  REWRITES,
  SMALL_CHANGES,
  type Act,
  type CastMember,
  type ComicPage,
  type Issue,
  type Purchase,
  type Role,
  type WriterMode,
} from "@/lib/comics/types";

const KEY = "perfect-comics-v1";
const COVER_PRICE = 2;
const ACT_PRICE = 6;
const ISSUE_PRICE = 20;

function money(n: number) {
  return Number.isInteger(n) ? `$${n}` : `$${n.toFixed(2)}`;
}

function blankPurchase(): Purchase {
  return { cover: false, beginning: false, middle: false, ending: false };
}

function owned(issue: Issue): Purchase {
  return { ...blankPurchase(), ...issue.purchase };
}

function due(p: Purchase) {
  return (p.cover ? 0 : COVER_PRICE) + (p.beginning ? 0 : ACT_PRICE) + (p.middle ? 0 : ACT_PRICE) + (p.ending ? 0 : ACT_PRICE);
}

function bookIsPaid(issue: Issue) {
  const p = owned(issue);
  return p.cover && p.beginning && p.middle && p.ending;
}

function comicNumber(issues: Issue[], currentId: string) {
  const prior = issues.filter((i) => i.id !== currentId && bookIsPaid(i)).length;
  return prior + 1;
}

function nextBlock(issue: Issue): keyof Purchase | null {
  const blocks: [keyof Purchase, number[]][] = [
    ["cover", [0]],
    ["beginning", [1, 2, 3]],
    ["middle", [4, 5, 6]],
    ["ending", [7, 8, 9]],
  ];
  for (const [part, nums] of blocks) {
    if (nums.some((n) => !issue.pages.find((p) => p.n === n)?.imageUrl)) return part;
  }
  return null;
}

function blockNums(part: keyof Purchase) {
  if (part === "cover") return [0];
  if (part === "beginning") return [1, 2, 3];
  if (part === "middle") return [4, 5, 6];
  return [7, 8, 9];
}

function unpaidBlock(issue: Issue): keyof Purchase | null {
  const order: (keyof Purchase)[] = ["cover", "beginning", "middle", "ending"];
  for (const part of order) {
    const hasArt = blockNums(part).some((n) => issue.pages.find((p) => p.n === n)?.imageUrl);
    if (hasArt && !owned(issue)[part]) return part;
  }
  return null;
}

function viewUrl(issue: Issue, page: ComicPage) {
  if (owned(issue)[page.act] && page.cleanUrl) return page.cleanUrl;
  return page.imageUrl;
}

function forSave(lib: Library): Library {
  return {
    ...lib,
    issues: lib.issues.map((issue) => {
      const own = owned(issue);
      return {
        ...issue,
        pages: issue.pages.map((page) => {
          if (own[page.act]) {
            return page.cleanUrl ? { ...page, imageUrl: page.cleanUrl, cleanUrl: undefined } : page;
          }
          if (!page.cleanUrl) return page;
          const { cleanUrl: _clean, ...rest } = page;
          return rest;
        }),
      };
    }),
  };
}

const POSE_LABELS = ["Front", "Left side", "Right side", "Back"] as const;

function shotsOf(member: { refUrl?: string; angles?: string[] }): string[] {
  const angles = (member.angles ?? []).filter(Boolean).slice(0, 4);
  if (angles.length) return angles;
  return member.refUrl ? [member.refUrl] : [];
}

async function loadImage(src: string): Promise<HTMLImageElement> {
  const res = await fetch(src);
  if (!res.ok) throw new Error("image");
  const blob = await res.blob();
  const local = URL.createObjectURL(blob);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("image"));
      el.src = local;
    });
  } finally {
    URL.revokeObjectURL(local);
  }
}

/** One page. Top row is one character's four saved shots. Bottom row is the other character's four. */
async function pairSheet(top: string[], bottom: string[]): Promise<string> {
  const res = await fetch(`${import.meta.env.BASE_URL}api/sheet`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ top: top.slice(0, 4), bottom: bottom.slice(0, 4) }),
  });
  const data = await res.json().catch(() => null);
  return data?.ok && typeof data.url === "string" ? data.url : "";
}

async function stamp(src: string): Promise<string> {
  try {
    const res = await fetch(src);
    if (!res.ok) return "";
    const blob = await res.blob();
    const local = URL.createObjectURL(blob);
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("stamp"));
      el.src = local;
    });
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return "";
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(-0.5);
    ctx.font = `800 ${Math.max(28, Math.round(canvas.width / 8))}px sans-serif`;
    ctx.textAlign = "center";
    ctx.lineWidth = Math.max(2, Math.round(canvas.width / 180));
    ctx.strokeStyle = "rgba(0,0,0,0.72)";
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    const step = Math.round(canvas.height / 4);
    for (let y = -canvas.height; y <= canvas.height; y += step) {
      ctx.strokeText("PERCFECT PREVIEW", 0, y);
      ctx.fillText("PERCFECT PREVIEW", 0, y);
    }
    ctx.restore();
    URL.revokeObjectURL(local);
    return canvas.toDataURL("image/jpeg", 0.72);
  } catch {
    return "";
  }
}

const TABS = ["Characters", "Cover", "Settings", "Summary", "Beginning", "Middle", "Ending", "Final Review"];

type Library = { currentId: string; issues: Issue[]; tickets: number; credits: number };

function normalize(issue: Issue): Issue {
  return {
    ...issue,
    purchase: owned(issue),
    editsLeft: { ...issue.editsLeft, cover: issue.editsLeft?.cover ?? 0, beginning: issue.editsLeft?.beginning ?? 0, middle: issue.editsLeft?.middle ?? 0, ending: issue.editsLeft?.ending ?? 0 },
  };
}

function load(): Library {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) {
      const issue = newIssue();
      return { currentId: issue.id, issues: [issue], tickets: 0, credits: 0 };
    }
    const parsed = JSON.parse(raw) as Library;
    if (!parsed.issues?.length) throw new Error("empty");
    return {
      ...parsed,
      credits: 0,
      issues: parsed.issues.map((issue) => normalize(issue)),
    };
  } catch {
    const issue = newIssue();
    return { currentId: issue.id, issues: [issue], tickets: 0, credits: 0 };
  }
}

function pageLabel(n: number) {
  if (n === 0) return "Cover";
  const act = n <= 3 ? "Beginning" : n <= 6 ? "Middle" : "Ending";
  return `${act} · page ${n}`;
}

function PageArt({ url, clean, alt, className }: { url: string; clean: boolean; alt: string; className?: string }) {
  return (
    <div className={`pageart${clean ? "" : " locked"}`}>
      <img className={className} src={url} alt={alt} />
      {!clean && (
        <div className="wm" aria-hidden>
          {Array.from({ length: 7 }, (_, i) => (
            <span key={i}>PERCFECT PREVIEW</span>
          ))}
        </div>
      )}
    </div>
  );
}

function shrinkRef(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const max = 768;
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        URL.revokeObjectURL(url);
        reject(new Error("canvas"));
        return;
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.72));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("image"));
    };
    img.src = url;
  });
}

export function Studio() {
  const [lib, setLib] = useState<Library | null>(null);
  const [tab, setTab] = useState(0);
  const [menu, setMenu] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [reader, setReader] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [look, setLook] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [refPhoto, setRefPhoto] = useState("");
  const [roster, setRoster] = useState<{ id: string; name: string; images: string[] }[]>([]);
  const [sheets, setSheets] = useState<string[]>([]);

  useEffect(() => {
    setLib(load());
    void fetch("/api/3d/library-characters", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const rows = Array.isArray(data?.characters) ? data.characters : [];
        setRoster(rows.map((row: { id: string; name?: string; images?: string[] }) => ({
          id: String(row.id),
          name: row.name || "Character",
          images: (row.images || []).filter((url: string) => typeof url === "string" && url).slice(0, 4),
        })));
      })
      .catch(() => setRoster([]));
  }, []);

  useEffect(() => {
    if (!lib) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(forSave(lib)));
    } catch {
      setError("Couldn't save that photo on this device. Try a smaller image.");
    }
  }, [lib]);

  const issue = lib?.issues.find((i) => i.id === lib.currentId) ?? null;
  const sheetKey = (issue?.characters ?? []).slice(0, 4).map((c) => shotsOf(c).join(",")).join("|");
  useEffect(() => {
    // Front-only path: one cast sheet with all four fronts
    if (issue?.castSheetUrl) {
      setSheets([issue.castSheetUrl]);
      return;
    }
    const people = (issue?.characters ?? []).slice(0, 4);
    let cancel = false;
    void (async () => {
      const made: string[] = [];
      for (let i = 0; i < people.length; i += 2) {
        const top = shotsOf(people[i]).slice(0, 4);
        const bottom = people[i + 1] ? shotsOf(people[i + 1]).slice(0, 4) : [];
        if (top.length < 4) continue;
        if (bottom.length && bottom.length < 4) continue;
        const sheet = await pairSheet(top, bottom);
        if (sheet) made.push(sheet);
      }
      if (!cancel) setSheets(made);
    })();
    return () => {
      cancel = true;
    };
  }, [sheetKey, issue?.castSheetUrl]);

  const issueRef = useRef<Issue | null>(null);
  issueRef.current = issue;

  function patch(fn: (issue: Issue) => Issue) {
    setLib((prev) => {
      if (!prev) return prev;
      const issues = prev.issues.map((i) => {
        if (i.id !== prev.currentId) return i;
        const next = { ...fn(i), updatedAt: new Date().toISOString() };
        issueRef.current = next;
        return next;
      });
      const nextLib = { ...prev, issues };
      try {
        localStorage.setItem(KEY, JSON.stringify(forSave(nextLib)));
      } catch {
        queueMicrotask(() => setError("Couldn't save that photo on this device. Try a smaller image."));
      }
      return nextLib;
    });
  }

  function patchPage(n: number, fn: (page: ComicPage) => ComicPage) {
    patch((issue) => ({ ...issue, pages: issue.pages.map((p) => (p.n === n ? fn(p) : p)) }));
  }

  function applyPurchaseLocal() {
    setLib((prev) => {
      if (!prev) return prev;
      const current = prev.issues.find((i) => i.id === prev.currentId);
      if (!current) return prev;
      const have = owned(current);
      const next: Purchase = { cover: true, beginning: true, middle: true, ending: true };
      const issues = prev.issues.map((i) => {
        if (i.id !== prev.currentId) return i;
        return {
          ...i,
          purchase: next,
          pages: i.pages.map((p) => (next[p.act] && !have[p.act] ? { ...p, editsLeft: 2 } : p)),
          updatedAt: new Date().toISOString(),
        };
      });
      const nextLib = { ...prev, credits: 0, issues };
      localStorage.setItem(KEY, JSON.stringify(forSave(nextLib)));
      return nextLib;
    });
  }

  /** Real Percfect wallet unlock. Free 5th charges 0. No more fake local unlock. */
  async function unlockBook(): Promise<string> {
    if (!issue || !lib) return "Open an issue first.";
    if (bookIsPaid(issue)) return "This comic is already unlocked.";
    const free = comicNumber(lib.issues, issue.id) % 5 === 0;
    setError("");
    setBusy("unlock");
    const result = await unlockIssue({ issueId: issue.id, free });
    setBusy(null);
    if (!result.ok) {
      setError(result.error);
      if (result.login_required) {
        return `${result.error} Sign in on PercfectAI, then say unlock again.`;
      }
      return result.error;
    }
    applyPurchaseLocal();
    if (result.free || result.charged === 0) {
      return "Unlocked as your free 5th comic. Clean pages and 2 edits per page are on.";
    }
    return `Unlocked for ${result.charged} credits. Balance ${result.credits}. Clean pages and 2 edits per page are on.`;
  }

  function ensureCastSlot(characters: CastMember[], slot: number): CastMember[] {
    const next = [...characters];
    while (next.length <= slot) {
      next.push({
        id: crypto.randomUUID(),
        name: `Character ${next.length + 1}`,
        look: "",
        role: "regular",
        angles: ["", "", "", ""],
      });
    }
    return next;
  }

  async function runChatVerb(verb: ChatVerb): Promise<string> {
    const live = issueRef.current;
    if (!live || !lib) return "Opening the press…";

    switch (verb.type) {
      case "help":
        return helpText({
          tab,
          title: live.title,
          castCount: live.characters.length,
          hasCoverPrompt: Boolean(live.pages[0]?.prompt?.trim()),
          hasCoverArt: Boolean(live.pages[0]?.imageUrl),
          coverApproved: Boolean(live.pages[0]?.approved),
          unlocked: bookIsPaid(live),
          priceLabel: comicNumber(lib.issues, live.id) % 5 === 0 ? "free 5th" : money(ISSUE_PRICE),
        });
      case "go": {
        const map = { characters: 0, cover: 1, settings: 2 } as const;
        setTab(map[verb.tab]);
        return `Opened ${verb.tab}.`;
      }
      case "set_title":
        patch((i) => ({ ...i, title: verb.title.slice(0, 80) }));
        return `Title set to “${verb.title.slice(0, 80)}”.`;
      case "set_style":
        patch((i) => ({ ...i, styleId: verb.styleId }));
        return `Print style is ${verb.label}.`;
      case "set_genre":
        patch((i) => ({ ...i, genre: verb.genre }));
        return `Genre is ${verb.genre}.`;
      case "add_library": {
        const q = verb.nameQuery.toLowerCase();
        const row = roster.find((r) => r.name.toLowerCase() === q)
          || roster.find((r) => r.name.toLowerCase().includes(q));
        if (!row) {
          const names = roster.filter((r) => r.images.length >= 4).map((r) => r.name).slice(0, 8);
          return names.length
            ? `No library match for “${verb.nameQuery}”. Try: ${names.join(", ")}.`
            : "No saved characters with four shots yet. Make four shots on Characters, or open the character library first.";
        }
        if (row.images.length < 4) {
          return `${row.name} needs four shots before they can join the sheet.`;
        }
        let added = false;
        patch((i) => {
          if (i.characters.length >= 4) return i;
          if (i.characters.some((c) => c.id === `lib-${row.id}`)) return i;
          added = true;
          const member: CastMember = {
            id: `lib-${row.id}`,
            name: row.name,
            look: "Saved in the library",
            role: "regular",
            refUrl: row.images[0],
            angles: row.images.slice(0, 4),
          };
          return { ...i, characters: [...i.characters, member] };
        });
        if (!added) {
          const cur = issueRef.current;
          if (cur && cur.characters.some((c) => c.id === `lib-${row.id}`)) {
            return `${row.name} is already on the cast.`;
          }
          return "Cast is full (four characters). Remove one first.";
        }
        return `Added ${row.name} from your library.`;
      }
      case "name_character": {
        if (verb.slot < 0 || verb.slot > 3) return "Use character 1 through 4.";
        patch((i) => {
          const characters = ensureCastSlot(i.characters, verb.slot).map((c, n) =>
            n === verb.slot ? { ...c, name: verb.name.slice(0, 80) } : c
          );
          return { ...i, characters };
        });
        return `Character ${verb.slot + 1} is named ${verb.name.slice(0, 80)}.`;
      }
      case "describe_character": {
        if (verb.slot < 0 || verb.slot > 3) return "Use character 1 through 4.";
        patch((i) => {
          const characters = ensureCastSlot(i.characters, verb.slot).map((c, n) =>
            n === verb.slot ? { ...c, look: verb.look.slice(0, 500) } : c
          );
          return { ...i, characters };
        });
        return `Got it for character ${verb.slot + 1}. On Characters you can still add a photo and make the four shots.`;
      }
      case "rewrite_cover": {
        setTab(1);
        await onRewrite("cover", live.pages[0]?.prompt ?? "", 0);
        return "Cover copy is ready. Say “ink cover” for the free watermarked draft.";
      }
      case "ink_cover": {
        setTab(1);
        const page = live.pages[0];
        if (!page) return "No cover page on this issue.";
        if (page.imageUrl) return "Cover already has art. Unlock for clean edits, or approve when you're happy.";
        await generateDrafts([0]);
        return "Inking the cover draft… check the Cover tab.";
      }
      case "approve_cover": {
        const page = live.pages[0];
        if (!page?.imageUrl) return "Ink the cover draft first.";
        approvePage(0);
        return "Cover approved. Beginning unlocks next.";
      }
      case "unlock":
        return unlockBook();
      case "unknown":
        return `I only run Characters and Cover moves right now. ${helpText({
          tab,
          title: live.title,
          castCount: live.characters.length,
          hasCoverPrompt: Boolean(live.pages[0]?.prompt?.trim()),
          hasCoverArt: Boolean(live.pages[0]?.imageUrl),
          coverApproved: Boolean(live.pages[0]?.approved),
          unlocked: bookIsPaid(live),
          priceLabel: comicNumber(lib.issues, live.id) % 5 === 0 ? "free 5th" : money(ISSUE_PRICE),
        })}`;
      default:
        return "Try “what's next?”";
    }
  }

  const castLine = useMemo(() => {
    if (!issue) return "";
    return issue.characters.map((c) => `${c.name}: ${c.look} (${c.role})`).join("; ");
  }, [issue]);

  async function onRewrite(target: "summary" | "beginning" | "middle" | "ending" | "cover" | "page", current: string, pageN?: number) {
    if (!issue) return;
    setError("");
    setBusy(`write-${target}-${pageN ?? ""}`);
    const result = await rewriteCopy({
      data: {
        target,
        title: issue.title || "My Percfect Hero",
        genre: issue.genre,
        styleId: issue.styleId,
        cast: castLine,
        current,
        invent: !current.trim(),
        context: issue.summary,
      },
    });
    setBusy(null);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    patch((i) => {
      const next = { ...i };
      if (target === "summary") {
        next.summary = result.text;
      } else if (target === "beginning" || target === "middle" || target === "ending") {
        next[target] = result.text;
        const start = target === "beginning" ? 1 : target === "middle" ? 4 : 7;
        const beats = result.pages || [];
        if (beats.length >= 3) {
          next.pages = i.pages.map((p) => {
            const slot = p.n - start;
            if (slot < 0 || slot > 2 || !beats[slot]) return p;
            return { ...p, prompt: beats[slot], status: p.imageUrl ? p.status : "ready" as const };
          });
        }
      } else if (target === "cover") {
        next.pages = i.pages.map((p) => (p.n === 0 ? { ...p, prompt: result.text, status: "ready" as const } : p));
      } else if (pageN != null) {
        next.pages = i.pages.map((p) => (p.n === pageN ? { ...p, prompt: result.text, status: "ready" as const } : p));
      }
      return next;
    });
  }

  async function ink(page: ComicPage, kind: "cover" | "interior" | "small" | "rewrite", note?: string) {
    const live = issueRef.current;
    if (!live) return;
    const current = live.pages.find((p) => p.n === page.n) ?? page;
    const part = current.act;
    const editing = kind === "small" || kind === "rewrite" || (current.imageUrl && kind === "cover");
    if (editing) {
      if (!owned(live)[part]) {
        setError("Pay to unlock the clean image. That leaves 2 edits. Three pictures total.");
        return;
      }
      if ((current.editsLeft ?? 0) <= 0) {
        setError("This page has used all 3 pictures.");
        return;
      }
      if (kind === "small" && !note?.trim()) {
        setError("Describe the small change — for example, green hat instead of red.");
        return;
      }
    }
    if (kind !== "small" && !current.prompt.trim()) {
      setError("Write what happens on this page first.");
      return;
    }
    if (kind !== "small" && kind !== "rewrite" && current.n > 0) {
      const prev = live.pages.find((p) => p.n === current.n - 1);
      if (!prev?.approved) {
        setError(`Approve ${pageLabel(current.n - 1)} first. The next page copies that picture.`);
        return;
      }
    }
    setError("");
    patchPage(current.n, (p) => ({ ...p, status: "inking", error: undefined }));
    setBusy(`ink-${current.n}`);
    const people = (() => {
      const ids = current.characterIds.length ? current.characterIds : live.characters.filter((c) => c.role === "regular").map((c) => c.id);
      const picked = live.characters.filter((c) => ids.includes(c.id));
      return picked.length ? picked : live.characters;
    })();
    const refs: string[] = [];
    let hasPrevPage = false;
    const fixing = editing && !!current.imageUrl;
    const onPage = people.slice(0, 4);
    const sheets: string[] = [];
    // Prefer the four-front cast sheet when that path is ready
    if (live.castSheetUrl) {
      sheets.push(live.castSheetUrl);
    } else {
      for (let i = 0; i < onPage.length; i += 2) {
        const top = shotsOf(onPage[i]);
        const bottom = onPage[i + 1] ? shotsOf(onPage[i + 1]) : [];
        if (top.length < 4) continue;
        if (bottom.length && bottom.length < 4) continue;
        const sheet = await pairSheet(top, bottom);
        if (sheet) sheets.push(sheet);
      }
    }
    // PageRef model: 1) cast sheet, 2) previous page, 3) optional extra (prop/location/costume).
    // Cover has no previous page — cast sheet (+ optional extra).
    if (fixing && current.imageUrl) {
      refs.push(...sheets.slice(0, 1));
      refs.push(current.imageUrl);
      if (current.extraRefUrl) refs.push(current.extraRefUrl);
    } else {
      refs.push(...sheets.slice(0, 1));
      const prev = live.pages.find((p) => p.n === current.n - 1);
      if (current.n > 0 && prev?.imageUrl) {
        refs.push(prev.imageUrl);
        hasPrevPage = true;
      }
      if (current.extraRefUrl) refs.push(current.extraRefUrl);
    }
    refs.splice(3); // ink API max 3 refs
    const actSummary = current.n === 0 ? live.summary : current.n <= 3 ? live.beginning : current.n <= 6 ? live.middle : live.ending;
    const result = await inkPage({
      data: {
        kind: fixing || kind === "small" ? "small" : current.n === 0 ? "cover" : "interior",
        page: current.n,
        title: live.title || "My Percfect Hero",
        issueNumber: live.issueNumber || 1,
        styleId: live.styleId,
        beat: current.prompt || live.summary || live.title,
        cast: people.map((c) => `${c.name}: ${c.look}`).join("; "),
        note: fixing && kind !== "small" ? current.prompt : note,
        actSummary,
        hasPrevPage,
        refs,
        model: "grok-imagine-image-2.0",
      },
    });
    setBusy(null);
    if (!result.ok) {
      patchPage(current.n, (p) => ({ ...p, status: "error", error: result.error }));
      setError(result.error);
      return;
    }
    patch((i) => ({
      ...i,
      pages: i.pages.map((p) => (p.n === current.n ? { ...p, status: "done", imageUrl: result.url, editsLeft: editing ? Math.max(0, (p.editsLeft ?? 0) - 1) : p.editsLeft, error: undefined } : p)),
    }));
  }

  async function generateDrafts(only?: number[]) {
    const live = issueRef.current;
    if (!live || busy) return;
    const allowed = live.pages.filter((p) => !p.imageUrl && (p.n === 0 || live.pages.find((prev) => prev.n === p.n - 1)?.approved)).map((p) => p.n);
    const nums = (only ?? allowed.slice(0, 1)).filter((n) => allowed.includes(n));
    if (!nums.length) return;
    setError("");
    if (nums.some((n) => !live.pages.find((p) => p.n === n)?.prompt.trim())) {
      setBusy("plan");
      const planned = await planBeats({
        data: {
          title: live.title || "My Percfect Hero",
          genre: live.genre,
          cast: live.characters.map((c) => `${c.name}: ${c.look}`).join("; "),
          summary: live.summary,
          beginning: live.beginning,
          middle: live.middle,
          ending: live.ending,
        },
      });
      const beats = planned.ok ? planned.beats : [];
      patch((issue) => ({
        ...issue,
        pages: issue.pages.map((p) => {
          if (!nums.includes(p.n) || p.imageUrl || p.prompt.trim()) return p;
          const beat = beats[p.n] || fallbackBeat(p.n, issue.summary, issue, issue.title);
          return { ...p, prompt: beat, status: "ready" as const };
        }),
      }));
      setBusy(null);
    }
    for (const n of nums) {
      const ready = issueRef.current?.pages.find((p) => p.n === n);
      if (!ready || ready.imageUrl) continue;
      await ink(ready, n === 0 ? "cover" : "interior");
      const after = issueRef.current?.pages.find((p) => p.n === n);
      if (after?.status === "error") break;
    }
  }

  function approvePage(n: number) {
    const live = issueRef.current;
    const page = live?.pages.find((p) => p.n === n);
    if (!page?.imageUrl) {
      setError("Generate this page before you approve it.");
      return;
    }
    setError("");
    patchPage(n, (p) => ({ ...p, approved: true }));
    if (n >= 9) setTab(7);
    else if (n === 0) setTab(4);
    else setTab(n + 1 <= 3 ? 4 : n + 1 <= 6 ? 5 : 6);
  }

  /** Front-only for speed. Sides/back come later. White-background full-body. */
  async function makeFrontShot(index: number): Promise<boolean> {
    const member = issueRef.current?.characters[index];
    const photo = member?.refUrl || "";
    if (!photo && !(member?.look || "").trim()) {
      setError("Drop a reference photo, or write what they look like.");
      return false;
    }
    setBusy(`front-${index}`);
    setError("");
    try {
      const res = await fetch(`${import.meta.env.BASE_URL}api/turnaround`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          styleId: issueRef.current?.styleId,
          name: member?.name || `Character ${index + 1}`,
          prompt: member?.look || "",
          photo,
          pose: "front",
        }),
      });
      const data = await res.json().catch(() => null);
      if (!data?.ok || typeof data.url !== "string") {
        throw new Error(data?.error || "Could not draw the front shot.");
      }
      patch((i) => ({
        ...i,
        castSheetUrl: undefined,
        characters: i.characters.map((c, n) => {
          if (n !== index) return c;
          const angles = ["", "", "", ""];
          angles[0] = data.url;
          return { ...c, angles, refUrl: c.refUrl || data.url };
        }),
      }));
      return true;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not draw the front shot.");
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function makeAllFronts() {
    const live = issueRef.current;
    if (!live || busy) return;
    const slots = [0, 1, 2, 3].filter((index) => {
      const c = live.characters[index];
      if (!c) return false;
      if (c.angles?.[0]) return false;
      return Boolean(c.refUrl || (c.look || "").trim());
    });
    if (!slots.length) {
      setError("Add up to four reference photos (or looks), then make fronts.");
      return;
    }
    for (const index of slots) {
      const ok = await makeFrontShot(index);
      if (!ok) break;
    }
    const after = issueRef.current;
    const fronts = (after?.characters || []).slice(0, 4).map((c) => c.angles?.[0] || "").filter(Boolean);
    if (fronts.length === 4) {
      await makeCastSheet();
    }
  }

  async function makeCastSheet() {
    const live = issueRef.current;
    if (!live) return;
    const fronts = live.characters.slice(0, 4).map((c) => c.angles?.[0] || "");
    if (fronts.some((u) => !u) || fronts.length < 4) {
      setError("Make a front shot for all four characters first.");
      return;
    }
    setBusy("cast-sheet");
    setError("");
    try {
      const result = await castSheet({ fronts });
      if (!result.ok) throw new Error(result.error || "Could not build the cast sheet.");
      patch((i) => ({ ...i, castSheetUrl: result.url }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not build the cast sheet.");
    } finally {
      setBusy(null);
    }
  }

  async function dropCastPhotos(files: FileList | File[] | null) {
    if (!files || busy) return;
    const list = Array.from(files).filter((f) => f.type.startsWith("image/")).slice(0, 4);
    if (!list.length) {
      setError("Drop JPG or PNG photos.");
      return;
    }
    setError("");
    const dataUrls: string[] = [];
    for (const file of list) {
      try {
        dataUrls.push(await shrinkRef(file));
      } catch {
        setError("One photo couldn't be read. Try JPG or PNG.");
        return;
      }
    }
    patch((i) => {
      const characters = [...i.characters];
      dataUrls.forEach((dataUrl, index) => {
        while (characters.length <= index) {
          characters.push({
            id: crypto.randomUUID(),
            name: `Character ${characters.length + 1}`,
            look: "",
            role: "regular",
            angles: ["", "", "", ""],
          });
        }
        characters[index] = {
          ...characters[index],
          refUrl: dataUrl,
          angles: ["", "", "", ""],
        };
      });
      return { ...i, characters: characters.slice(0, 4), castSheetUrl: undefined };
    });
  }

  async function saveCharacter(member: CastMember) {
    const images = shotsOf(member).slice(0, 4);
    if (images.length < 4) {
      setError("Each character needs four pictures: front, left side, right side, and back.");
      return;
    }
    setBusy("save-character");
    setError("");
    try {
      const res = await fetch(`${import.meta.env.BASE_URL}api/save-character`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: member.name, look: member.look, images }),
      });
      const data = await res.json().catch(() => null);
      if (!data?.ok || !data.id) throw new Error(data?.error || "Could not save the character.");
      const savedImages = (data.images as string[]) || images;
      patch((i) => ({
        ...i,
        characters: i.characters.map((c) => c.id === member.id ? {
          ...c,
          id: `lib-${data.id}`,
          name: data.name || c.name,
          refUrl: savedImages[0],
          angles: savedImages,
        } : c),
      }));
      setRoster((rows) => [{ id: String(data.id), name: data.name || member.name, images: savedImages }, ...rows]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not save the character.");
    } finally {
      setBusy(null);
    }
  }

  function addCharacter() {
    if (!name.trim()) return;
    patch((i) => {
      if (i.characters.length >= 5) return i;
      const member: CastMember = {
        id: crypto.randomUUID(),
        name: name.trim(),
        look: look.trim() || "original costume",
        role: i.isSeries ? "regular" : "oneshot",
        refUrl: refPhoto || (/^https?:\/\//i.test(refUrl.trim()) ? refUrl.trim() : undefined),
      };
      return { ...i, characters: [...i.characters, member] };
    });
    setName("");
    setLook("");
    setRefUrl("");
    setRefPhoto("");
  }

  async function readRefPhoto(file: File | undefined, apply: (dataUrl: string) => void) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Upload a JPG or PNG.");
      return;
    }
    setError("");
    try {
      apply(await shrinkRef(file));
    } catch {
      setError("That photo couldn't be read. Try a JPG or PNG.");
    }
  }

  function setRole(id: string, role: Role) {
    patch((i) => ({ ...i, characters: i.characters.map((c) => (c.id === id ? { ...c, role } : c)) }));
  }

  function toggleOnPage(pageN: number, id: string) {
    patchPage(pageN, (p) => {
      const has = p.characterIds.includes(id);
      return { ...p, characterIds: has ? p.characterIds.filter((x) => x !== id) : [...p.characterIds, id] };
    });
  }

  function openPage(n: number) {
    if (n !== 0) patch((i) => ({ ...i, mode: "pageByPage" }));
    setReader(false);
    setTab(n === 0 ? 1 : n <= 3 ? 4 : n <= 6 ? 5 : 6);
    window.setTimeout(() => {
      document.getElementById(`page-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  if (!lib || !issue) {
    return <main className="subhead" style={{ padding: 32 }}>Opening the press…</main>;
  }

  const style = styleById(issue.styleId);
  const nextPart = nextBlock(issue);
  const bookNo = comicNumber(lib.issues, issue.id);
  const freeBook = bookNo % 5 === 0;
  const acts: { act: Exclude<Act, "cover">; tab: number; pages: number[] }[] = [
    { act: "beginning", tab: 4, pages: [1, 2, 3] },
    { act: "middle", tab: 5, pages: [4, 5, 6] },
    { act: "ending", tab: 6, pages: [7, 8, 9] },
  ];

  return (
    <>
      <header className="topline">
        <div className={`logo-nav${menu ? " open" : ""}`}>
          <button className="logo-btn" aria-expanded={menu} onClick={() => setMenu((v) => !v)}>
            <img className="logo" src={`${import.meta.env.BASE_URL}logo-clear.png`} alt="PercfectAI" />
          </button>
          <div className="dropdown">
            <button className="on" type="button" onClick={() => setMenu(false)}>Comics</button>
            <div className="sep" />
            <button type="button" onClick={() => { setLibraryOpen(true); setMenu(false); }}>Library</button>
          </div>
        </div>
      </header>

      <div className="studiotabs">
        <button className={!reader ? "on" : ""} type="button" onClick={() => setReader(false)}>Studio</button>
        <button className={reader ? "on" : ""} type="button" onClick={() => { setReader(true); setTab(7); }}>Reader</button>
      </div>

      {!reader && (
        <>
          <div className="allow" aria-live="polite">
            Rewrites left <b className={issue.rewritesLeft <= 0 ? "out" : ""}>{issue.rewritesLeft}</b> of {REWRITES}
            <span className="allow__sep">·</span>
            Small changes left <b className={issue.smallChangesLeft <= 0 ? "out" : ""}>{issue.smallChangesLeft}</b> of {SMALL_CHANGES}
          </div>
          <div className="wtabs">
            {TABS.map((label, i) => (
              <button key={label} className={`wtab${tab === i ? " on" : ""}`} type="button" onClick={() => setTab(i)}>
                <span className="num">{i}</span> {label}
              </button>
            ))}
          </div>
        </>
      )}

      <div className="wrap">
        <div>
          {reader ? (
            <section className="subpage on">
              <div>
                <div className="kicker">Reader</div>
                <h1 className="head">{issue.title || "My Percfect Hero"}</h1>
                <p className="subhead">{issue.summary || "No synopsis yet."}</p>
              </div>
              <div className="reader">
                {issue.pages.map((p) => (
                  <figure key={p.n}>
                    {p.imageUrl ? <PageArt url={p.imageUrl} clean={owned(issue)[p.act]} alt={pageLabel(p.n)} /> : <div className="picph">Not inked</div>}
                    <figcaption>{pageLabel(p.n)}</figcaption>
                  </figure>
                ))}
              </div>
            </section>
          ) : (
            <>
              <section className={`subpage${tab === 2 ? " on" : ""}`}>
                <div>
                  <div className="kicker">Settings</div>
                  <h1 className="head">Set the issue. <span className="cr">Then write it.</span></h1>
                  <p className="subhead">Ten pages. A comic is {money(ISSUE_PRICE)}. Four of them are {money(ISSUE_PRICE * 4)} over time, and the 5th is free.</p>
                </div>
                <div className="pricehint">
                  <div className="t">{freeBook ? `Comic ${bookNo} · Free` : `Comic ${bookNo} · ${money(ISSUE_PRICE)}`}</div>
                  <div className="d">
                    {freeBook
                      ? `You already paid ${money(ISSUE_PRICE * 4)} for four comics. This 5th one is free. Claim it and the pages come off watermark. Then it starts over at ${money(ISSUE_PRICE)}.`
                      : `This is comic ${bookNo}. Each one is ${money(ISSUE_PRICE)} when you finish it. Comics 1–4 are ${money(ISSUE_PRICE * 4)} over time. Comic 5 is free, then it repeats.`}
                  </div>
                </div>
                <div className="block">
                  <div className="label">Is this a series?</div>
                  <div className="choices">
                    <button className={`choice${!issue.isSeries ? " sel" : ""}`} type="button" onClick={() => patch((i) => ({ ...i, isSeries: false }))}>
                      <div className="t">One-shot</div><div className="d">{freeBook ? "This one is free" : money(ISSUE_PRICE)}</div>
                    </button>
                    <button className={`choice${issue.isSeries ? " sel" : ""}`} type="button" onClick={() => patch((i) => ({ ...i, isSeries: true }))}>
                      <div className="t">Series</div><div className="d">{freeBook ? "This one is free" : money(ISSUE_PRICE)}</div>
                    </button>
                  </div>
                </div>
                {issue.isSeries && (
                  <div className="block">
                    <div className="label">Series name</div>
                    <input className="inp" maxLength={80} placeholder="Skywake" value={issue.seriesName} onChange={(e) => patch((i) => ({ ...i, seriesName: e.target.value }))} />
                  </div>
                )}
                <div className="block">
                  <div className="label">Title this issue</div>
                  <div className="row2">
                    <input className="inp" maxLength={80} placeholder="My Percfect Hero" value={issue.title} onChange={(e) => patch((i) => ({ ...i, title: e.target.value }))} />
                    {issue.isSeries && (
                      <input className="inp" type="number" min={1} value={issue.issueNumber} aria-label="Issue number" onChange={(e) => patch((i) => ({ ...i, issueNumber: Math.max(1, Number(e.target.value) || 1) }))} />
                    )}
                  </div>
                </div>
                <div className="block">
                  <div className="label">Genre</div>
                  <div className="chips">
                    {GENRES.map((g) => (
                      <button key={g} className={`chip${issue.genre === g ? " sel" : ""}`} type="button" onClick={() => patch((i) => ({ ...i, genre: g }))}>{g}</button>
                    ))}
                  </div>
                </div>
                <div className="block">
                  <div className="label">Print style</div>
                  <div className="styles">
                    {STYLES.map((s) => (
                      <button
                        key={s.id}
                        className={`style${issue.styleId === s.id ? " sel" : ""}`}
                        type="button"
                        onClick={() => patch((i) => ({ ...i, styleId: s.id as StyleId }))}
                      >
                        <div className="sn">{s.label}</div>
                        <div className="sb">{s.blurb}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </section>

              <section className={`subpage${tab === 3 ? " on" : ""}`}>
                <div>
                  <div className="kicker">Summary</div>
                  <h1 className="head">The whole issue, in a breath.</h1>
                  <p className="subhead">One synopsis. Craft fills an empty box. Rewrite tidies what you typed.</p>
                </div>
                <PromptBox
                  value={issue.summary}
                  placeholder="Stakes and hook for the whole issue"
                  busy={busy === "write-summary-"}
                  locked={false}
                  onChange={(v) => patch((i) => ({ ...i, summary: v }))}
                  onRewrite={() => onRewrite("summary", issue.summary)}
                />
              </section>

              <section className={`subpage${tab === 0 ? " on" : ""}`}>
                <div>
                  <div className="kicker">1 · Characters</div>
                  <h1 className="head">Four fronts. One sheet.</h1>
                  <p className="subhead">
                    Drop up to four reference photos. We draw a full-body front on white for each, then build one cast reference page with all four.
                  </p>
                </div>
                <div className="block">
                  <div className="label">Print style for these fronts</div>
                  <div className="styles">
                    {STYLES.map((s) => (
                      <button
                        key={s.id}
                        className={`style${issue.styleId === s.id ? " sel" : ""}`}
                        type="button"
                        onClick={() => patch((i) => ({ ...i, styleId: s.id as StyleId, castSheetUrl: undefined }))}
                      >
                        <div className="sn">{s.label}</div>
                        <div className="sb">{s.blurb}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="block">
                  <div className="label">Drop references</div>
                  <label
                    className="castdrop"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      void dropCastPhotos(e.dataTransfer.files);
                    }}
                  >
                    <span>Drop 1–4 photos here, or tap to pick</span>
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      multiple
                      onChange={(e) => {
                        const files = e.target.files;
                        e.target.value = "";
                        void dropCastPhotos(files);
                      }}
                    />
                  </label>
                  <div className="cast__actions">
                    <button className="btn-sm primary" type="button" disabled={!!busy} onClick={() => void makeAllFronts()}>
                      {busy?.startsWith("front") ? "Drawing fronts…" : "Make all fronts"}
                    </button>
                    <button
                      className="btn-sm primary"
                      type="button"
                      disabled={
                        !!busy ||
                        issue.characters.slice(0, 4).length < 4 ||
                        issue.characters.slice(0, 4).some((c) => !c.angles?.[0])
                      }
                      onClick={() => void makeCastSheet()}
                    >
                      {busy === "cast-sheet" ? "Building sheet…" : "Make cast reference sheet"}
                    </button>
                  </div>
                  <p className="help">Sides and back come later. Right now: front only, then one page with all four.</p>
                </div>
                {issue.castSheetUrl && (
                  <div className="block castsheet">
                    <div className="label">Cast reference sheet</div>
                    <img src={issue.castSheetUrl} alt="Four character fronts on one page" />
                  </div>
                )}
                <div className="block">
                  <div className="label">Characters</div>
                  <div className="cast__grid">
                    {roster.filter((row) => row.images.length >= 1).map((row) => (
                      <button
                        key={row.id}
                        className="btn-sm"
                        type="button"
                        onClick={() => patch((i) => {
                          if (i.characters.length >= 4) return i;
                          if (i.characters.some((c) => c.id === `lib-${row.id}`)) return i;
                          const front = row.images[0];
                          const member: CastMember = {
                            id: `lib-${row.id}`,
                            name: row.name,
                            look: "Saved in the library",
                            role: "regular",
                            refUrl: front,
                            angles: [front, "", "", ""],
                          };
                          return { ...i, characters: [...i.characters, member], castSheetUrl: undefined };
                        })}
                      >
                        Use saved {row.name}
                      </button>
                    ))}
                  </div>
                  <div className="caststack">
                    {[0, 1, 2, 3].map((index) => {
                      const c = issue.characters[index];
                      const front = c?.angles?.[0] || "";
                      const saved = Boolean(c?.id.startsWith("lib-"));
                      const touch = (apply: (characters: CastMember[]) => CastMember[]) => patch((i) => {
                        const characters = [...i.characters];
                        while (characters.length <= index) {
                          characters.push({ id: crypto.randomUUID(), name: `Character ${characters.length + 1}`, look: "", role: "regular", angles: ["", "", "", ""] });
                        }
                        return { ...i, characters: apply(characters), castSheetUrl: undefined };
                      });
                      return (
                        <article key={c?.id || `slot-${index}`} className="castrow">
                          <div className="label">Character {index + 1}</div>
                          <input className="inp" value={c?.name || ""} placeholder={`Character ${index + 1}`} onChange={(e) => touch((characters) => characters.map((x, n) => n === index ? { ...x, name: e.target.value } : x))} />
                          <textarea className="inp" rows={2} placeholder="Optional details — face, outfit, hair." value={c?.look || ""} onChange={(e) => touch((characters) => characters.map((x, n) => n === index ? { ...x, look: e.target.value } : x))} />
                          {!saved && (
                            <label className="refshot">
                              {c?.refUrl ? <img src={c.refUrl} alt="" /> : <span>Reference photo{"\n"}drop or tap</span>}
                              <input
                                type="file"
                                accept="image/png,image/jpeg,image/webp"
                                onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  e.target.value = "";
                                  void readRefPhoto(file, (dataUrl) => {
                                    touch((characters) => characters.map((x, n) => n === index ? { ...x, refUrl: dataUrl, angles: ["", "", "", ""] } : x));
                                  });
                                }}
                              />
                            </label>
                          )}
                          {!saved && (
                            <button className="btn-sm primary" type="button" disabled={!!busy} onClick={() => void makeFrontShot(index)}>
                              {busy === `front-${index}` ? "Drawing front…" : "Make front"}
                            </button>
                          )}
                          <div className="shotrow shotrow--front">
                            <div className="shotshow">
                              {front ? <img src={front} alt="Front" /> : <span>Front</span>}
                            </div>
                          </div>
                          {c && <button className="btn-sm" type="button" onClick={() => patch((i) => ({ ...i, characters: i.characters.filter((x) => x.id !== c.id), castSheetUrl: undefined }))}>Remove</button>}
                        </article>
                      );
                    })}
                  </div>
                </div>
              </section>

              <section className={`subpage${tab === 1 ? " on" : ""}`}>
                <PageRail issue={issue} pageN={0}>
                <CoverBlock
                  issue={issue}
                  sheets={sheets}
                  busy={busy}
                  onApprove={() => approvePage(0)}
                  onPrompt={(v) => patchPage(0, (p) => ({ ...p, prompt: v, status: v.trim() ? "ready" : "draft" }))}
                  onRewrite={() => onRewrite("cover", issue.pages[0]?.prompt ?? "", 0)}
                  onToggle={(id) => toggleOnPage(0, id)}
                  belowPrompt={null}
                  onInk={() => {
                    const page = issue.pages[0];
                    if (page && !page.imageUrl) void generateDrafts([0]);
                  }}
                  onSmall={(note) => {
                    const page = issue.pages[0];
                    if (page) void ink(page, "small", note);
                  }}
                  onRewriteImage={() => {
                    const page = issue.pages[0];
                    if (page) void ink(page, "rewrite");
                  }}
                  onBuy={() => void unlockBook()}
                  onExtraRef={(dataUrl) => patchPage(0, (p) => ({ ...p, extraRefUrl: dataUrl }))}
                  onClearExtra={() => patchPage(0, (p) => {
                    const { extraRefUrl: _drop, ...rest } = p;
                    return rest;
                  })}
                  freeBook={freeBook}
                />
                </PageRail>
              </section>

              {acts.map(({ act, tab: t, pages }) => (
                <section key={act} className={`subpage${tab === t ? " on" : ""}`}>
                  <ActBlock
                    act={act}
                    pages={pages}
                    issue={issue}
                    sheets={sheets}
                    busy={busy}
                    onSummary={(v) => patch((i) => ({ ...i, [act]: v }))}
                    onMode={(mode: WriterMode) => patch((i) => ({ ...i, mode }))}
                    onRewriteSummary={() => onRewrite(act, issue[act])}
                    onSplitPages={() => onRewrite(act, issue[act])}
                    onPrompt={(n, v) => patchPage(n, (p) => ({ ...p, prompt: v, status: p.imageUrl ? p.status : v.trim() ? "ready" : "draft" }))}
                    onRewritePage={(n) => {
                      const page = issue.pages.find((p) => p.n === n);
                      void onRewrite("page", page?.prompt ?? "", n);
                    }}
                    onExtraRef={(n, dataUrl) => patchPage(n, (p) => ({ ...p, extraRefUrl: dataUrl }))}
                    onClearExtra={(n) => patchPage(n, (p) => {
                      const { extraRefUrl: _drop, ...rest } = p;
                      return rest;
                    })}
                    onToggle={toggleOnPage}
                    onInk={(n) => {
                      const page = issue.pages.find((p) => p.n === n);
                      if (page && !page.imageUrl) void ink(page, "interior");
                    }}
                    onApprove={(n) => approvePage(n)}
                    onSmall={(n, note) => {
                      const page = issue.pages.find((p) => p.n === n);
                      if (page) void ink(page, "small", note);
                    }}
                    onRewriteImage={(n) => {
                      const page = issue.pages.find((p) => p.n === n);
                      if (page) void ink({ ...page }, "rewrite");
                    }}
                    onBuy={() => void unlockBook()}
                    onGenerate={() => {
                      const next = pages.find((n) => {
                        const page = issue.pages.find((p) => p.n === n);
                        const prev = issue.pages.find((p) => p.n === n - 1);
                        return page && !page.imageUrl && prev?.approved;
                      });
                      if (next == null) {
                        setError("Approve the page before this one. The next page copies that picture.");
                        return;
                      }
                      const page = issue.pages.find((p) => p.n === next);
                      if (page) void ink(page, "interior");
                    }}
                    freeBook={freeBook}
                  />
                </section>
              ))}

              <section className={`subpage${tab === 7 ? " on" : ""}`}>
                <div>
                  <div className="kicker">Final Review</div>
                  <h1 className="head">{issue.title || "My Percfect Hero"}</h1>
                  <p className="subhead">
                    {issue.isSeries ? `${issue.seriesName || "Untitled"} #${issue.issueNumber} · ` : "One-shot · "}
                    {issue.genre} · {style.label}. Cover, then pages 1–9. Click a page to edit it.
                  </p>
                </div>
                {issue.summary.trim() ? <p className="subhead">{issue.summary}</p> : <p className="help">No issue summary yet.</p>}
                <div className="chips">
                  {issue.characters.length === 0 && <span className="help">No cast yet.</span>}
                  {issue.characters.map((c) => (
                    <span key={c.id} className="chip sel">{c.name}</span>
                  ))}
                </div>
                {(() => {
                  const missing = issue.pages.filter((p) => !p.prompt.trim() || !p.imageUrl);
                  if (!missing.length) return null;
                  return (
                    <div className="errbox">
                      Still open: {missing.map((p) => `${pageLabel(p.n)}${p.prompt.trim() ? "" : " (no prompt)"}${p.imageUrl ? "" : " (not inked)"}`).join(" · ")}
                    </div>
                  );
                })()}
                <div className="review">
                  {issue.pages.map((p) => (
                    <button
                      key={p.n}
                      className={`rev${p.n === 0 ? " cover" : ""}`}
                      type="button"
                      onClick={() => openPage(p.n)}
                    >
                      <div className="rev__img">
                        {p.imageUrl ? <PageArt url={p.imageUrl} clean={owned(issue)[p.act]} alt="" /> : pageLabel(p.n)}
                      </div>
                      <div className="rev__cap">{pageLabel(p.n)} · {p.imageUrl ? "inked" : "not inked"}</div>
                      <div className="rev__beat">{p.prompt.trim() || "No prompt yet"}</div>
                    </button>
                  ))}
                </div>
                <p className="help">Each page is drawn after you approve the one before it. A mistake on page 2 would be copied onto every page after it.</p>
                {due(owned(issue)) > 0 ? (
                  <button className="btn-publish" type="button" onClick={() => void unlockBook()}>
                    {freeBook ? "Claim this free comic · 2 edits per page" : `Purchase full comic · ${money(due(owned(issue)))} · 2 edits per page`}
                  </button>
                ) : (
                  <p className="help">{freeBook ? "Free comic. These pages are clean." : "Purchased. These pages are clean."}</p>
                )}
                <button
                  className="btn-publish"
                  type="button"
                  disabled={issue.pages.some((p) => !p.imageUrl)}
                  onClick={() => {
                    patch((i) => ({ ...i, published: true }));
                    setReader(true);
                  }}
                >
                  Publish issue
                </button>
              </section>
            </>
          )}
        </div>

        {tab === 0 || tab === 1 ? (
          <ChatRail
            busy={!!busy}
            context={{
              tab,
              title: issue.title,
              castCount: issue.characters.length,
              hasCoverPrompt: Boolean(issue.pages[0]?.prompt?.trim()),
              hasCoverArt: Boolean(issue.pages[0]?.imageUrl),
              coverApproved: Boolean(issue.pages[0]?.approved),
              unlocked: bookIsPaid(issue),
              priceLabel: freeBook ? "free 5th" : money(ISSUE_PRICE),
            }}
            runVerb={runChatVerb}
          />
        ) : (
          <aside className="samplecover">
            <img src={`${import.meta.env.BASE_URL}example-cover.jpg`} alt="Example comic cover" />
          </aside>
        )}
      </div>

      <div className="pricedock">
        {error && <div className="errbox">{error}</div>}
        <span>{freeBook ? `Comic ${bookNo} · Free` : `${money(ISSUE_PRICE)} a comic`}</span>
        {!reader && tab < 7 && (
          <button className="btn-sm primary" type="button" onClick={() => setTab(tab + 1)}>Next</button>
        )}
      </div>

      <button className="libfab" type="button" aria-label="Open library" onClick={() => setLibraryOpen(true)}>
        <img src={`${import.meta.env.BASE_URL}crownp.png`} alt="" />
      </button>

      <div className="modal" hidden={!libraryOpen}>
        <div className="modal__backdrop" onClick={() => setLibraryOpen(false)} />
        <div className="modal__panel">
          <div className="modal__head">
            <h3>Library — The Rack</h3>
            <button className="modal__x" type="button" onClick={() => setLibraryOpen(false)}>✕</button>
          </div>
          <button
            className="btn-sm primary"
            type="button"
            onClick={() => {
              const fresh = newIssue();
              setLib((prev) => prev ? { ...prev, currentId: fresh.id, issues: [fresh, ...prev.issues] } : prev);
              setTab(0);
              setReader(false);
              setLibraryOpen(false);
            }}
          >
            New issue
          </button>
          {lib.issues.map((i) => (
            <button
              key={i.id}
              className="librow"
              type="button"
              onClick={() => {
                setLib((prev) => prev ? { ...prev, currentId: i.id } : prev);
                setLibraryOpen(false);
                setReader(false);
              }}
            >
              <span>
                <div className="nm">{i.title || "Untitled issue"}</div>
                <div className="meta">{i.genre} · {styleById(i.styleId).label} · {i.published ? "Published" : "Draft"}</div>
              </span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="trow"><span className="k">{k}</span><span className="v">{v}</span></div>
  );
}

function PromptBox({
  value,
  placeholder,
  busy,
  locked,
  onChange,
  onRewrite,
}: {
  value: string;
  placeholder: string;
  busy: boolean;
  locked: boolean;
  onChange: (v: string) => void;
  onRewrite: () => void;
}) {
  return (
    <div className="pbox">
      <textarea value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {!value.trim() && (
        <button className="pbox__craft" type="button" disabled={busy || locked} onClick={onRewrite}>Craft from scratch</button>
      )}
      <button className="pbox__rewrite" type="button" disabled={busy || locked} onClick={onRewrite}>
        {busy ? "Writing…" : "AI rewrite"}
      </button>
    </div>
  );
}

function RefLock({
  pageN,
  pages,
  sheets,
  onExtraRef,
  onClearExtra,
}: {
  pageN: number;
  pages: ComicPage[];
  sheets: string[];
  onExtraRef?: (dataUrl: string) => void;
  onClearExtra?: () => void;
}) {
  const page = pages.find((p) => p.n === pageN);
  const prev = pageN > 0 ? pages.find((p) => p.n === pageN - 1) : undefined;
  const cells = [
    { title: "Ref 1 · cast sheet", src: sheets[0], empty: "Make four fronts, then the cast reference sheet" },
    {
      title: pageN === 0 ? "Ref 2 · (cover has no prior page)" : `Ref 2 · ${pageN - 1 === 0 ? "cover" : `page ${pageN - 1}`}`,
      src: pageN === 0 ? undefined : prev?.imageUrl,
      empty: pageN === 0 ? "Cover only needs the cast sheet (+ optional extra)" : "Approve the page before this one",
    },
    {
      title: "Ref 3 · optional extra",
      src: page?.extraRefUrl,
      empty: "Prop, location, or costume — only if needed",
      optional: true as const,
    },
  ];
  return (
    <div className="reflock">
      {cells.map((cell) => (
        <figure key={cell.title}>
          {cell.src ? (
            <img src={cell.src} alt="" />
          ) : "optional" in cell && cell.optional && onExtraRef ? (
            <label className="reflock__drop">
              <span>{cell.empty}</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file || !file.type.startsWith("image/")) return;
                  void shrinkRef(file)
                    .then((dataUrl) => onExtraRef(dataUrl))
                    .catch(() => undefined);
                }}
              />
            </label>
          ) : (
            <div className="reflock__ph">{cell.empty}</div>
          )}
          <figcaption>
            {cell.title}
            {"optional" in cell && cell.optional && page?.extraRefUrl && onClearExtra ? (
              <>
                {" · "}
                <button type="button" className="linkish" onClick={onClearExtra}>
                  clear
                </button>
              </>
            ) : null}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function PageRail({ issue, pageN, children }: { issue: Issue; pageN: number; children: ReactNode }) {
  const page = issue.pages.find((p) => p.n === pageN);
  const ids = page?.characterIds.length ? page.characterIds : issue.characters.filter((c) => c.role === "regular").map((c) => c.id);
  const picked = issue.characters.filter((c) => ids.includes(c.id));
  const fronts = (picked.length ? picked : issue.characters).slice(0, 4);
  return (
    <div className="pagerow">
      <aside className="castrail" aria-label="Characters on this page">
        {fronts.length === 0 && <p className="help">Add up to four characters.</p>}
        {fronts.map((c) => (
          <figure key={c.id} className="railshot">
            {c.angles?.[0] ? <img src={c.angles[0]} alt="" /> : <span>Front</span>}
            <figcaption>{c.name}</figcaption>
          </figure>
        ))}
      </aside>
      <div className="pagecol">{children}</div>
    </div>
  );
}

function CoverBlock({
  issue,
  sheets,
  busy,
  onPrompt,
  onRewrite,
  onToggle,
  onInk,
  onSmall,
  onRewriteImage,
  onBuy,
  onApprove,
  onExtraRef,
  onClearExtra,
  freeBook,
  belowPrompt,
}: {
  issue: Issue;
  sheets: string[];
  busy: string | null;
  belowPrompt?: ReactNode;
  onApprove: () => void;
  onPrompt: (v: string) => void;
  onRewrite: () => void;
  onToggle: (id: string) => void;
  onInk: () => void;
  onSmall: (note: string) => void;
  onRewriteImage: () => void;
  onBuy: () => void;
  onExtraRef: (dataUrl: string) => void;
  onClearExtra: () => void;
  freeBook: boolean;
}) {
  const page = issue.pages[0];
  const [note, setNote] = useState("");
  return (
    <div id="page-0">
      <div>
        <div className="kicker">2 · Cover</div>
        <h1 className="head">Cover</h1>
        <p className="subhead">The cast sheet from Characters is the face bible for this cover. Name any of them in the prompt.</p>
      </div>
      <div className="block">
        <div className="label">Cast reference sheet</div>
        {sheets[0] ? (
          <img src={sheets[0]} alt="Four character fronts" style={{ width: "100%", maxWidth: 420, borderRadius: 12 }} />
        ) : (
          <p className="help">On Characters: drop four photos → Make all fronts → cast reference sheet. Then the cover can ink.</p>
        )}
      </div>
      <div className="block">
        <div className="label">Who's on the cover</div>
        <div className="chips">
          {issue.characters.length === 0 && <span className="help">Add characters on the Characters page.</span>}
          {issue.characters.map((c) => (
            <button key={c.id} className={`chip${page?.characterIds.includes(c.id) ? " sel" : ""}`} type="button" onClick={() => onToggle(c.id)}>{c.name}</button>
          ))}
        </div>
      </div>
      <PromptBox
        value={page?.prompt ?? ""}
        placeholder="Cover idea. Name any character from the Characters page."
        busy={busy === "write-cover-0"}
        locked={false}
        onChange={onPrompt}
        onRewrite={onRewrite}
      />
      {belowPrompt}
      <RefLock
        pageN={0}
        pages={issue.pages}
        sheets={sheets}
        onExtraRef={onExtraRef}
        onClearExtra={onClearExtra}
      />
      {page?.imageUrl && <PageArt url={page.imageUrl} clean={owned(issue).cover} alt="Cover" className="pageimg" />}
      <p className="help">The first draft is free and watermarked. That is picture 1 of 3. Unlock it for 2 edits. All three use the 2.0 model.</p>
      {!page?.imageUrl && (
        <button className="btn-genpage" type="button" disabled={!!busy || !sheets[0]} onClick={onInk}>Generate this cover</button>
      )}
      {page?.imageUrl && !page.approved && (
        <button className="btn-publish" type="button" onClick={onApprove}>Approve cover and open page 1</button>
      )}
      {page?.approved && <p className="help">Cover approved. Page 1 uses this picture as its reference.</p>}
      {page?.imageUrl && !owned(issue).cover && (
        <button className="btn-publish" type="button" onClick={onBuy}>{freeBook ? "Unlock this free comic · 2 edits a page" : `Unlock this comic · ${money(ISSUE_PRICE)}`}</button>
      )}
      {page?.imageUrl && owned(issue).cover && (
        <p className="help">{page.editsLeft ?? 0} edits left.</p>
      )}
      {page?.imageUrl && owned(issue).cover && (
        <div className="editrow">
          <input className="inp" placeholder="Small change — keep the rest of the cover" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="rowbtns">
            <button className="btn-smchg" type="button" disabled={!!busy || (page.editsLeft ?? 0) <= 0} onClick={() => onSmall(note)}>Small change</button>
            <button className="btn-rew" type="button" disabled={!!busy || (page.editsLeft ?? 0) <= 0} onClick={onRewriteImage}>Use an edit</button>
          </div>
        </div>
      )}
      {page?.error && <div className="errbox">{page.error}</div>}
    </div>
  );
}

function ActBlock({
  act,
  pages,
  issue,
  sheets,
  busy,
  onSummary,
  onMode,
  onRewriteSummary,
  onSplitPages,
  onPrompt,
  onRewritePage,
  onExtraRef,
  onClearExtra,
  onToggle,
  onInk,
  onSmall,
  onRewriteImage,
  onBuy,
  onGenerate,
  onApprove,
  freeBook,
}: {
  act: "beginning" | "middle" | "ending";
  pages: number[];
  issue: Issue;
  sheets: string[];
  busy: string | null;
  onSummary: (v: string) => void;
  onMode: (m: WriterMode) => void;
  onRewriteSummary: () => void;
  onSplitPages: () => void;
  onPrompt: (n: number, v: string) => void;
  onRewritePage: (n: number) => void;
  onExtraRef: (n: number, dataUrl: string) => void;
  onClearExtra: (n: number) => void;
  onToggle: (n: number, id: string) => void;
  onInk: (n: number) => void;
  onSmall: (n: number, note: string) => void;
  onRewriteImage: (n: number) => void;
  onBuy: () => void;
  onGenerate: () => void;
  onApprove: (n: number) => void;
  freeBook: boolean;
}) {
  const [notes, setNotes] = useState<Record<number, string>>({});
  const summary = issue[act];
  void onMode;
  return (
    <>
      <div>
        <div className="kicker">{act} · pages {pages[0]}–{pages[2]}</div>
        <h1 className="head">Write the {act}.</h1>
        <p className="subhead">Write one act summary, then split it into three page beats. Ink uses the cast sheet, the previous page, and an optional extra ref.</p>
      </div>
      <PromptBox
        value={summary}
        placeholder={`${act} — what happens across these three pages`}
        busy={busy === `write-${act}-`}
        locked={false}
        onChange={onSummary}
        onRewrite={onRewriteSummary}
      />
      <div className="cast__actions">
        <button
          className="btn-sm primary"
          type="button"
          disabled={!!busy || !summary.trim()}
          onClick={onSplitPages}
        >
          {busy === `write-${act}-` ? "Splitting…" : "Split into 3 pages"}
        </button>
      </div>
      <p className="help">Split fills the three page prompts below. Approve a page before the next one is drawn — that picture becomes ref 2.</p>
      <button className="btn-genpage" type="button" disabled={!!busy || pages.every((n) => issue.pages.find((p) => p.n === n)?.imageUrl)} onClick={onGenerate}>
        {pages.every((n) => issue.pages.find((p) => p.n === n)?.imageUrl) ? "These pages are drawn" : "Generate the next page"}
      </button>
      {pages.some((n) => issue.pages.find((p) => p.n === n)?.imageUrl) && !owned(issue)[act] && (
        <button className="btn-publish" type="button" onClick={onBuy}>{freeBook ? "Unlock this free comic · 2 edits a page" : `Unlock this comic · ${money(ISSUE_PRICE)}`}</button>
      )}
      {true && (
        <>
          <div className="actsum">
            <div className="t">{act} summary</div>
            <div className="s">{summary.trim() || `Add the ${act} above and it pins here.`}</div>
          </div>
          {pages.map((n) => {
            const page = issue.pages.find((p) => p.n === n)!;
            const prev = issue.pages.find((p) => p.n === n - 1);
            return (
              <PageRail key={n} issue={issue} pageN={n}>
              <article className="pcard" id={`page-${n}`}>
                <div className="pcard__hd">
                  <span className="pcard__no">Page {n}</span>
                  <span className={`pstat ${page.status}`}>{page.status}</span>
                </div>
                <div className="pcard__body">
                  <div className="pcard__main">
                    <PromptBox
                      value={page.prompt}
                      placeholder={`Page ${n} — who is here, what we see, how the page ends`}
                      busy={busy === `write-page-${n}`}
                      locked={false}
                      onChange={(v) => onPrompt(n, v)}
                      onRewrite={() => onRewritePage(n)}
                    />
                    {prev?.imageUrl && (
                      <figure className="lookback">
                        <figcaption>{n === 1 ? "Cover" : `Page ${n - 1}`} — look back while you write this page</figcaption>
                        <PageArt url={prev.imageUrl} clean={owned(issue)[prev.act]} alt="" />
                      </figure>
                    )}
                    <RefLock
                      pageN={n}
                      pages={issue.pages}
                      sheets={sheets}
                      onExtraRef={(dataUrl) => onExtraRef(n, dataUrl)}
                      onClearExtra={() => onClearExtra(n)}
                    />
                    <div>
                      <span className="label">Who's on this page</span>
                      <div className="chips">
                        {issue.characters.map((c) => (
                          <button key={c.id} className={`chip${page.characterIds.includes(c.id) ? " sel" : ""}`} type="button" onClick={() => onToggle(n, c.id)}>{c.name}</button>
                        ))}
                      </div>
                    </div>
                    {!page.imageUrl && !issue.pages.find((p) => p.n === n - 1)?.approved && (
                      <p className="help">Approve {n === 1 ? "the cover" : `page ${n - 1}`} before this page can be drawn.</p>
                    )}
                    {!page.imageUrl && !!issue.pages.find((p) => p.n === n - 1)?.approved && (
                      <button className="btn-genpage" type="button" disabled={!!busy} onClick={() => onInk(n)}>Generate this page</button>
                    )}
                    {page.imageUrl && !page.approved && (
                      <button className="btn-publish" type="button" onClick={() => onApprove(n)}>
                        {n < 9 ? `Approve page ${n} and open the next` : "Approve the last page"}
                      </button>
                    )}
                    {page.approved && <p className="help">Approved. The next page uses this picture.</p>}
                    {page.imageUrl && owned(issue)[act] && (
                      <div className="editrow">
                        <input className="inp" placeholder="Small change — green hat instead of red, keep the rest" value={notes[n] ?? ""} onChange={(e) => setNotes((s) => ({ ...s, [n]: e.target.value }))} />
                        <div className="rowbtns">
                          <button className="btn-smchg" type="button" disabled={!!busy || (page.editsLeft ?? 0) <= 0} onClick={() => onSmall(n, notes[n] ?? "")}>Small change</button>
                          <button className="btn-rew" type="button" disabled={!!busy || (page.editsLeft ?? 0) <= 0} onClick={() => onRewriteImage(n)}>Use an edit</button>
                        </div>
                        <div className="caps">{page.editsLeft ?? 0} edits left.</div>
                      </div>
                    )}
                    {page.error && <div className="errbox">{page.error}</div>}
                  </div>
                  <div>
                    {page.imageUrl ? <PageArt url={page.imageUrl} clean={owned(issue)[act]} alt="" className="pageimg" /> : <div className="picph">Page {n}<br />not inked</div>}
                  </div>
                </div>
              </article>
              </PageRail>
            );
          })}
        </>
      )}
    </>
  );
}
