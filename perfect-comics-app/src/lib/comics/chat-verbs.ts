import { GENRES, STYLES, type StyleId } from "./catalog";

/** Allowlisted chat verbs for Characters + Cover (slice 1). */
export type ChatVerb =
  | { type: "help" }
  | { type: "go"; tab: "characters" | "cover" | "settings" }
  | { type: "set_title"; title: string }
  | { type: "set_style"; styleId: StyleId; label: string }
  | { type: "set_genre"; genre: string }
  | { type: "add_library"; nameQuery: string }
  | { type: "name_character"; slot: number; name: string }
  | { type: "describe_character"; slot: number; look: string }
  | { type: "rewrite_cover" }
  | { type: "ink_cover" }
  | { type: "approve_cover" }
  | { type: "unlock" }
  | { type: "unknown"; raw: string };

const TAB_ALIASES: Record<string, ChatVerb["type"] extends never ? never : "characters" | "cover" | "settings"> = {
  characters: "characters",
  character: "characters",
  cast: "characters",
  cover: "cover",
  settings: "settings",
  setting: "settings",
};

function clean(s: string) {
  return s.trim().replace(/\s+/g, " ");
}

function matchStyle(text: string): { styleId: StyleId; label: string } | null {
  const low = text.toLowerCase();
  for (const s of STYLES) {
    if (low.includes(s.id) || low.includes(s.label.toLowerCase())) {
      return { styleId: s.id, label: s.label };
    }
  }
  // loose aliases
  if (/\bmanga\b/.test(low)) return { styleId: "anime", label: "Anime" };
  if (/\bpencil\b/.test(low)) return { styleId: "sketch", label: "Pencil sketch" };
  if (/\bneon\b/.test(low)) return { styleId: "cyberpunk", label: "Cyberpunk neon" };
  return null;
}

function matchGenre(text: string): string | null {
  const low = text.toLowerCase();
  for (const g of GENRES) {
    if (low.includes(g.toLowerCase())) return g;
  }
  return null;
}

/** Rule-based router — no extra model call. Rewrite/ink still use existing APIs. */
export function parseChatVerb(input: string): ChatVerb {
  const raw = clean(input);
  const low = raw.toLowerCase();
  if (!raw) return { type: "help" };

  if (
    /^(help|hi|hello|\?)$/i.test(raw) ||
    /\bwhat(?:'s| is)? next\b/.test(low) ||
    /\b(how do i|what can you)\b/.test(low)
  ) {
    return { type: "help" };
  }

  if (/\b(unlock|purchase|buy|pay|checkout)\b/.test(low) && /\b(comic|book|issue|cover|it|this|full)?\b/.test(low)) {
    return { type: "unlock" };
  }
  if (/^(unlock|buy|purchase)(\s+(the\s+)?(comic|book|issue))?$/i.test(raw)) {
    return { type: "unlock" };
  }

  if (/\bapprove\b/.test(low) && /\bcover\b/.test(low)) return { type: "approve_cover" };

  if (/\b(ink|draw|generate|make)\b/.test(low) && /\bcover\b/.test(low)) return { type: "ink_cover" };

  if (/\b(rewrite|craft|write)\b/.test(low) && /\bcover\b/.test(low)) return { type: "rewrite_cover" };
  if (/^(rewrite|craft)(\s+cover)?$/i.test(raw)) return { type: "rewrite_cover" };

  const go = low.match(/\b(?:go(?:\s+to)?|open|show|switch(?:\s+to)?)\s+(characters?|cast|cover|settings?)\b/);
  if (go) {
    const key = go[1].replace(/s$/, "").replace("character", "characters");
    const tab =
      key.startsWith("character") || key === "cast"
        ? "characters"
        : key.startsWith("setting")
          ? "settings"
          : "cover";
    return { type: "go", tab };
  }
  if (/^(characters?|cast|cover|settings?)$/i.test(raw)) {
    const k = raw.toLowerCase();
    if (k.startsWith("character") || k === "cast") return { type: "go", tab: "characters" };
    if (k.startsWith("setting")) return { type: "go", tab: "settings" };
    return { type: "go", tab: "cover" };
  }

  const title =
    raw.match(/^(?:set\s+)?title(?:\s+(?:is|to|:))?\s+(.+)$/i) ||
    raw.match(/^call(?:\s+it)?\s+(.+)$/i) ||
    raw.match(/^name(?:\s+the)?\s+(?:issue|comic|book)\s+(.+)$/i);
  if (title?.[1]) return { type: "set_title", title: clean(title[1]).replace(/^["']|["']$/g, "") };

  if (/\b(style|print style)\b/.test(low) || /^(use|set)\s+\w+/i.test(raw)) {
    const style = matchStyle(raw);
    if (style && (/\bstyle\b/.test(low) || /^(use|set)\s+/i.test(raw))) {
      return { type: "set_style", ...style };
    }
  }
  const styleOnly = matchStyle(raw);
  if (styleOnly && /^(classic|anime|realistic|noir|pixel|cyberpunk)\b/i.test(raw)) {
    return { type: "set_style", ...styleOnly };
  }

  if (/\bgenre\b/.test(low)) {
    const genre = matchGenre(raw);
    if (genre) return { type: "set_genre", genre };
  }
  const genreOnly = matchGenre(raw);
  if (genreOnly && new RegExp(`^${genreOnly}$`, "i").test(raw)) {
    return { type: "set_genre", genre: genreOnly };
  }

  const addLib =
    raw.match(/\b(?:add|use|pick|load)\s+(?:saved\s+|library\s+)?(.+?)(?:\s+from\s+(?:the\s+)?library)?$/i) ||
    raw.match(/^use\s+saved\s+(.+)$/i);
  if (addLib?.[1] && /\b(add|use|pick|load|saved|library)\b/i.test(raw) && !/\bcover\b/i.test(raw)) {
    const nameQuery = clean(addLib[1]).replace(/\s+from\s+(the\s+)?library$/i, "");
    if (nameQuery && !/^(the|a|an)$/i.test(nameQuery)) {
      return { type: "add_library", nameQuery };
    }
  }

  const nameChar =
    raw.match(/(?:name|call)\s+character\s*([1-4])\s+(?:is\s+|to\s+|:\s*)?(.+)$/i) ||
    raw.match(/character\s*([1-4])\s*(?:'s)?\s*name\s+(?:is\s+|to\s+|:\s*)?(.+)$/i);
  if (nameChar) {
    return { type: "name_character", slot: Number(nameChar[1]) - 1, name: clean(nameChar[2]).replace(/^["']|["']$/g, "") };
  }

  const descChar =
    raw.match(/(?:describe|set)\s+character\s*([1-4])\s*(?:to|:)?\s*(.+)$/i) ||
    raw.match(/character\s*([1-4])\s*(?:looks?\s+like|is|:)\s+(.+)$/i);
  if (descChar) {
    return { type: "describe_character", slot: Number(descChar[1]) - 1, look: clean(descChar[2]) };
  }

  void TAB_ALIASES;
  return { type: "unknown", raw };
}

export function helpText(ctx: {
  tab: number;
  title: string;
  castCount: number;
  hasCoverPrompt: boolean;
  hasCoverArt: boolean;
  coverApproved: boolean;
  unlocked: boolean;
  priceLabel: string;
}): string {
  const bits: string[] = [];
  bits.push("I drive Characters and Cover for you. Try:");
  bits.push('• "title is Skywake"');
  bits.push('• "style anime" or "genre Fantasy"');
  bits.push('• "use saved Maya" (library character)');
  bits.push('• "character 1 is a red-coat detective"');
  bits.push('• "go to cover" → "rewrite cover" → "ink cover"');
  bits.push(`• "unlock" (${ctx.priceLabel}, real Percfect credits)`);
  bits.push('• "approve cover" when the draft looks right');

  const next: string[] = [];
  if (!ctx.title.trim() || ctx.title === "My Percfect Hero") next.push("set a title");
  if (ctx.castCount < 1) next.push("add a library character or describe character 1");
  if (ctx.tab === 0 && ctx.castCount >= 1) next.push('say "go to cover"');
  if (!ctx.hasCoverPrompt) next.push('say "rewrite cover"');
  else if (!ctx.hasCoverArt) next.push('say "ink cover" for the free watermarked draft');
  else if (!ctx.unlocked) next.push('say "unlock" for the clean book + 2 edits a page');
  else if (!ctx.coverApproved) next.push('say "approve cover"');
  else next.push("move into Beginning when you're ready");

  bits.push("");
  bits.push(`Next up: ${next[0]}.`);
  return bits.join("\n");
}
