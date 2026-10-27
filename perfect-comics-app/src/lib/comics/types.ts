import type { StyleId } from "./catalog";

export type Role = "regular" | "recurring" | "oneshot";
export type Act = "cover" | "beginning" | "middle" | "ending";
export type PageStatus = "draft" | "ready" | "inking" | "done" | "error";
export type WriterMode = "quick" | "pageByPage";

export type CastMember = {
  id: string;
  name: string;
  look: string;
  role: Role;
  refUrl?: string;
};

export type ComicPage = {
  /** 0 = cover, 1–9 = interiors labeled Page 1–9 */
  n: number;
  act: Act;
  prompt: string;
  characterIds: string[];
  status: PageStatus;
  imageUrl?: string;
  /** Clean file. Kept in memory until the block is claimed, then it replaces imageUrl. */
  cleanUrl?: string;
  /** Paid edits left on this page. Granted when its block is unlocked. */
  editsLeft?: number;
  /** Page-by-page only. The next page stays closed until this is true. */
  approved?: boolean;
  error?: string;
};

export type Purchase = {
  cover: boolean;
  beginning: boolean;
  middle: boolean;
  ending: boolean;
};

export type BlockEdits = {
  cover: number;
  beginning: number;
  middle: number;
  ending: number;
};

export type Issue = {
  id: string;
  title: string;
  isSeries: boolean;
  seriesName: string;
  issueNumber: number;
  genre: string;
  styleId: StyleId;
  summary: string;
  beginning: string;
  middle: string;
  ending: string;
  mode: WriterMode;
  characters: CastMember[];
  pages: ComicPage[];
  rewritesLeft: number;
  smallChangesLeft: number;
  published: boolean;
  purchase: Purchase;
  /** Edits granted when that block is unlocked. 3 per unlock. */
  editsLeft: BlockEdits;
  updatedAt: string;
};

export const REWRITES = 3;
export const SMALL_CHANGES = 7;

export function blankPages(): ComicPage[] {
  const pages: ComicPage[] = [
    { n: 0, act: "cover", prompt: "", characterIds: [], status: "draft" },
  ];
  const acts: Act[] = ["beginning", "beginning", "beginning", "middle", "middle", "middle", "ending", "ending", "ending"];
  acts.forEach((act, i) => {
    pages.push({ n: i + 1, act, prompt: "", characterIds: [], status: "draft" });
  });
  return pages;
}

export function newIssue(): Issue {
  return {
    id: crypto.randomUUID(),
    title: "",
    isSeries: false,
    seriesName: "",
    issueNumber: 1,
    genre: "Adventure",
    styleId: "classic",
    summary: "",
    beginning: "",
    middle: "",
    ending: "",
    mode: "quick",
    characters: [],
    pages: blankPages(),
    rewritesLeft: REWRITES,
    smallChangesLeft: SMALL_CHANGES,
    published: false,
    purchase: { cover: false, beginning: false, middle: false, ending: false },
    editsLeft: { cover: 0, beginning: 0, middle: 0, ending: 0 },
    updatedAt: new Date().toISOString(),
  };
}

export function actTextKey(act: Exclude<Act, "cover">): "beginning" | "middle" | "ending" {
  return act;
}
