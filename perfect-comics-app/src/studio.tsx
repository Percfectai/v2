import { useEffect, useMemo, useRef, useState } from "react";
import { STYLES, styleById, type StyleId } from "@/lib/comics/catalog";
import { GENRES } from "@/lib/comics/catalog";
import { inkPage, planBeats, rewriteCopy } from "@/lib/comics/ai.functions";
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

const TABS = ["Settings", "Character Reference", "Summary", "Cover", "Beginning", "Middle", "Ending", "Final Review"];

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
  const [tab, setTab] = useState(3);
  const [menu, setMenu] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [reader, setReader] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [hoverStyle, setHoverStyle] = useState<string | null>(null);
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
    const people = (issue?.characters ?? []).slice(0, 4);
    let cancel = false;
    void (async () => {
      const made: string[] = [];
      for (let i = 0; i < people.length; i += 2) {
        const top = shotsOf(people[i]).slice(0, 4);
        const bottom = people[i + 1] ? shotsOf(people[i + 1]).slice(0, 4) : [];
        if (top.length < 4 || bottom.length < 4) continue;
        const sheet = await pairSheet(top, bottom);
        if (sheet) made.push(sheet);
      }
      if (!cancel) setSheets(made);
    })();
    return () => {
      cancel = true;
    };
  }, [sheetKey]);

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

  function buy(part: keyof Purchase | "all") {
    if (!issue || !lib) return;
    if (bookIsPaid(issue)) return;
    const free = comicNumber(lib.issues, issue.id) % 5 === 0;
    const have = owned(issue);
    const next: Purchase = { cover: true, beginning: true, middle: true, ending: true };
    if (!free && due(have) <= 0) return;
    setError("");
    setLib((prev) => {
      if (!prev) return prev;
      const current = prev.issues.find((i) => i.id === prev.currentId);
      if (!current) return prev;
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
      if (target === "summary" || target === "beginning" || target === "middle" || target === "ending") {
        next[target] = result.text;
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
    for (let i = 0; i < onPage.length; i += 2) {
      const top = shotsOf(onPage[i]);
      const bottom = onPage[i + 1] ? shotsOf(onPage[i + 1]) : [];
      if (!top.length && !bottom.length) continue;
      const sheet = await pairSheet(top, bottom);
      if (sheet) sheets.push(sheet);
    }
    if (fixing && current.imageUrl) {
      refs.push(current.imageUrl, ...sheets.slice(0, 2));
    } else {
      const prev = live.pages.find((p) => p.n === current.n - 1);
      if (current.n > 0 && prev?.imageUrl) {
        refs.push(prev.imageUrl);
        hasPrevPage = true;
      }
      refs.push(...sheets.slice(0, Math.max(0, 3 - refs.length)));
    }
    const actSummary = current.n === 0 ? live.summary : current.n <= 3 ? live.beginning : current.n <= 6 ? live.middle : live.ending;
    const result = await inkPage({
      data: {
        kind: fixing || kind === "small" ? "small" : current.n === 0 ? "cover" : "interior",
        page: current.n,
        title: live.title || "My Percfect Hero",
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
    setTab(n === 0 ? 3 : n <= 3 ? 4 : n <= 6 ? 5 : 6);
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
        <div className="wallet">
          <span className="chip-w cr"><span className="dot cr" />{money(ISSUE_PRICE)} a comic</span>
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
              <section className={`subpage${tab === 0 ? " on" : ""}`}>
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
                        onMouseEnter={() => setHoverStyle(s.label)}
                        onMouseLeave={() => setHoverStyle(null)}
                        onClick={() => patch((i) => ({ ...i, styleId: s.id as StyleId }))}
                      >
                        <div className="sn">{s.label}</div>
                        <div className="sb">{s.blurb}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </section>

              <section className={`subpage${tab === 2 ? " on" : ""}`}>
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

              <section className={`subpage${tab === 1 ? " on" : ""}`}>
                <div>
                  <div className="kicker">Character Reference</div>
                  <h1 className="head">Lock the cast.</h1>
                  <p className="subhead">Two characters share one sheet: angles on the top half, the other character on the bottom. A page with those two uses the page before it and that one sheet. Four characters use the page before it, then a sheet of the first pair and a sheet of the second pair.</p>
                </div>
                <div className="label">From your character library</div>
                <p className="help">Pick two saved characters. Their pictures are pasted onto one page: one character across the top, the other across the bottom. That single page is the reference.</p>
                <div className="cast__grid">
                  {roster.filter((row) => row.images.length >= 4).map((row) => (
                    <article key={row.id} className="castcard">
                      <img className="castthumb" src={row.images[0]} alt="" />
                      <div className="nm">{row.name}</div>
                      <div className="lk">Saved character</div>
                      <button
                        className="btn-sm primary"
                        type="button"
                        onClick={() => patch((i) => {
                          if (i.characters.length >= 4) return i;
                          if (i.characters.some((c) => c.id === `lib-${row.id}`)) return i;
                          const member: CastMember = {
                            id: `lib-${row.id}`,
                            name: row.name,
                            look: "Library character",
                            role: "regular",
                            refUrl: row.images[0],
                            angles: row.images.slice(0, 4),
                          };
                          return { ...i, characters: [...i.characters, member] };
                        })}
                      >
                        Add to the sheet
                      </button>
                    </article>
                  ))}
                  {roster.filter((row) => row.images.length >= 4).length === 0 && (
                    <p className="help">No finished character with four shots is on this account yet. Make one on the character page first.</p>
                  )}
                </div>
                {sheets.map((src, i) => (
                  <figure key={src.slice(0, 48)} className="block">
                    <div className="label">{i === 0 ? "Sprite card A — characters 1 and 2" : "Sprite card B — characters 3 and 4"}</div>
                    <p className="help">Four shots on top, four shots on the bottom. This whole card is one of the three pictures sent with each page.</p>
                    <img src={src} alt="Two characters, four shots each" style={{ width: "100%", maxWidth: 640, borderRadius: 12 }} />
                  </figure>
                ))}
                <div className="label">Cast — {issue.characters.length} / 5</div>
                <div className="cast__grid">
                  {issue.characters.map((c) => (
                    <article key={c.id} className="castcard">
                      {c.refUrl && <img className="castthumb" src={c.refUrl} alt="" />}
                      <div className="nm">{c.name}</div>
                      <div className="lk">{c.look}</div>
                      {issue.isSeries && (
                        <div className="chips" style={{ marginTop: 8 }}>
                          {(["regular", "recurring", "oneshot"] as Role[]).map((r) => (
                            <button key={r} className={`chip${c.role === r ? " sel" : ""}`} type="button" onClick={() => setRole(c.id, r)}>
                              {r === "regular" ? "Every issue" : r === "recurring" ? "In and out" : "This issue only"}
                            </button>
                          ))}
                        </div>
                      )}
                      <label className="btn-sm upload">
                        {c.refUrl ? "Replace photo" : "Upload photo"}
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            e.target.value = "";
                            void readRefPhoto(file, (dataUrl) => {
                              patch((i) => ({
                                ...i,
                                characters: i.characters.map((x) => (x.id === c.id ? { ...x, refUrl: dataUrl } : x)),
                              }));
                            });
                          }}
                        />
                      </label>
                      <button className="btn-sm" style={{ marginTop: 8 }} type="button" onClick={() => patch((i) => ({ ...i, characters: i.characters.filter((x) => x.id !== c.id) }))}>Remove</button>
                    </article>
                  ))}
                  {issue.characters.length < 5 && (
                    <div className="slot">
                      <input className="inp" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
                      <input className="inp" placeholder="Look — jacket, mask, hair" value={look} onChange={(e) => setLook(e.target.value)} />
                      <label className="btn-sm upload primary">
                        {refPhoto ? "Photo ready — tap to change" : "Upload reference photo"}
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            e.target.value = "";
                            void readRefPhoto(file, setRefPhoto);
                          }}
                        />
                      </label>
                      {refPhoto && <img className="castthumb" src={refPhoto} alt="" />}
                      <input className="inp" placeholder="Or paste an image link" value={refUrl} onChange={(e) => setRefUrl(e.target.value)} />
                      <button className="btn-sm primary" type="button" onClick={addCharacter}>Add to cast</button>
                    </div>
                  )}
                </div>
              </section>

              <section className={`subpage${tab === 3 ? " on" : ""}`}>
                <CoverBlock
                  issue={issue}
                  sheets={sheets}
                  busy={busy}
                  onApprove={() => approvePage(0)}
                  onPrompt={(v) => patchPage(0, (p) => ({ ...p, prompt: v, status: v.trim() ? "ready" : "draft" }))}
                  onRewrite={() => onRewrite("cover", issue.pages[0]?.prompt ?? "", 0)}
                  onToggle={(id) => toggleOnPage(0, id)}
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
                  onBuy={() => buy("all")}
                  freeBook={freeBook}
                />
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
                    onPrompt={(n, v) => patchPage(n, (p) => ({ ...p, prompt: v, status: p.imageUrl ? p.status : v.trim() ? "ready" : "draft" }))}
                    onRewritePage={(n) => {
                      const page = issue.pages.find((p) => p.n === n);
                      void onRewrite("page", page?.prompt ?? "", n);
                    }}
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
                    onBuy={() => buy("all")}
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
                  <button className="btn-publish" type="button" onClick={() => buy("all")}>
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

        <aside className="ticket">
          <div className="ticket__still">
            <div className="ph">Style preview</div>
            <span className="ticket__chip">{hoverStyle ?? style.label}</span>
          </div>
          <div className="ticket__body">
            <h3 className="ticket__title">Print ticket</h3>
            <Row k={issue.isSeries ? "Series" : "Format"} v={issue.isSeries ? `${issue.seriesName || "Untitled"} #${issue.issueNumber}` : "One-shot"} />
            <Row k="Title" v={issue.title || "My Percfect Hero"} />
            <Row k="Genre" v={issue.genre} />
            <Row k="Style" v={style.label} />
            <Row k="Pages" v="Cover + 9 · 10" />
            <Row k="Cast" v={`${issue.characters.length} / 5`} />
            <div className="trow price"><span className="k">This comic</span><span className="v">{freeBook ? "Free" : money(ISSUE_PRICE)}</span></div>
            <p className="help" style={{ marginTop: 8 }}>
              {freeBook
                ? `Comic ${bookNo} is free. Four paid comics were ${money(ISSUE_PRICE * 4)}.`
                : `Comic ${bookNo} is ${money(ISSUE_PRICE)}. Four comics are ${money(ISSUE_PRICE * 4)} over time. The 5th is free.`}
            </p>
            <div className="nextpage">Rewrites left <b>{issue.rewritesLeft}</b> of {REWRITES} · Small changes left <b>{issue.smallChangesLeft}</b> of {SMALL_CHANGES}</div>
            {error && <div className="errbox">{error}</div>}
            {tab < 7 && (
              <button className="btn-gen" type="button" onClick={() => setTab(tab + 1)}>
                Next
              </button>
            )}
          </div>
        </aside>
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

function RefLock({ pageN, pages, sheets }: { pageN: number; pages: ComicPage[]; sheets: string[] }) {
  const prev = pageN > 0 ? pages.find((p) => p.n === pageN - 1) : undefined;
  const cells = [
    { title: "Ref 1 · previous page", src: prev?.imageUrl, empty: pageN === 0 ? "Cover uses the cards only" : "Approve the page before this one" },
    { title: "Ref 2 · card A", src: sheets[0], empty: "Needs characters 1 and 2, four shots each" },
    { title: "Ref 3 · card B", src: sheets[1], empty: "Only if characters 3 and 4 are both on the sheet" },
  ];
  return (
    <div className="reflock">
      {cells.map((cell) => (
        <figure key={cell.title}>
          {cell.src ? <img src={cell.src} alt="" /> : <div className="reflock__ph">{cell.empty}</div>}
          <figcaption>{cell.title}</figcaption>
        </figure>
      ))}
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
  freeBook,
}: {
  issue: Issue;
  sheets: string[];
  busy: string | null;
  onApprove: () => void;
  onPrompt: (v: string) => void;
  onRewrite: () => void;
  onToggle: (id: string) => void;
  onInk: () => void;
  onSmall: (note: string) => void;
  onRewriteImage: () => void;
  onBuy: () => void;
  freeBook: boolean;
}) {
  const page = issue.pages[0];
  const [note, setNote] = useState("");
  return (
    <div id="page-0">
      <div>
        <div className="kicker">Cover</div>
        <h1 className="head">One dramatic splash.</h1>
        <p className="subhead">A single cover image. No panels. No lettering on the art.</p>
      </div>
      <div className="block">
        <div className="label">Who's on the cover</div>
        <div className="chips">
          {issue.characters.length === 0 && <span className="help">Add cast in Character Reference.</span>}
          {issue.characters.map((c) => (
            <button key={c.id} className={`chip${page?.characterIds.includes(c.id) ? " sel" : ""}`} type="button" onClick={() => onToggle(c.id)}>{c.name}</button>
          ))}
        </div>
      </div>
      <PromptBox
        value={page?.prompt ?? ""}
        placeholder="Cover idea — single splash"
        busy={busy === "write-cover-0"}
        locked={false}
        onChange={onPrompt}
        onRewrite={onRewrite}
      />
      <RefLock pageN={0} pages={issue.pages} sheets={sheets} />
      {page?.imageUrl && <PageArt url={page.imageUrl} clean={owned(issue).cover} alt="Cover" className="pageimg" />}
      <p className="help">The first draft is free and watermarked. That is picture 1 of 3. Unlock it for 2 edits. All three use the 2.0 model.</p>
      {!page?.imageUrl && (
        <button className="btn-genpage" type="button" disabled={!!busy} onClick={onInk}>Generate this cover</button>
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
  onPrompt,
  onRewritePage,
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
  onPrompt: (n: number, v: string) => void;
  onRewritePage: (n: number) => void;
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
  return (
    <>
      <div>
        <div className="kicker">{act} · pages {pages[0]}–{pages[2]}</div>
        <h1 className="head">Write the {act}.</h1>
        <p className="subhead">First drafts are free and watermarked. You can ink every page. Edits wait until you unlock the page.</p>
      </div>
      <PromptBox
        value={summary}
        placeholder={`${act} — what happens across these three pages`}
        busy={busy === `write-${act}-`}
        locked={false}
        onChange={onSummary}
        onRewrite={onRewriteSummary}
      />
      <p className="help">Approve a page before the next one is drawn. The next page copies the picture you approved.</p>
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
            return (
              <article key={n} className="pcard" id={`page-${n}`}>
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
                    <RefLock pageN={n} pages={issue.pages} sheets={sheets} />
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
            );
          })}
        </>
      )}
    </>
  );
}
