import { SAFETY, styleById } from "./catalog";

export type InkKind = "cover" | "interior" | "small";

export type InkBrief = {
  kind: InkKind;
  /** 0 = cover, 1–9 = interiors */
  page: number;
  title: string;
  styleId: string;
  beat: string;
  cast: string;
  note?: string;
  actSummary?: string;
  hasPrevPage: boolean;
};

export function fallbackBeat(page: number, summary: string, acts: { beginning: string; middle: string; ending: string }, title: string): string {
  const hook = summary.trim() || title.trim() || "An original hero in trouble";
  if (page === 0) return `Cover splash of the lead, mid-action, selling this story: ${hook}`;
  const act = page <= 3 ? acts.beginning : page <= 6 ? acts.middle : acts.ending;
  const stage = page <= 3 ? "the opening" : page <= 6 ? "the turn" : "the finish";
  const step = page <= 3 ? page : page <= 6 ? page - 3 : page - 6;
  const source = act.trim() || hook;
  return `Page ${page}, ${stage}, beat ${step} of 3. Show a new moment that advances this, and do not repeat an earlier page: ${source}`;
}

export function buildInkPrompt(brief: InkBrief): string {
  const style = styleById(brief.styleId).prompt;
  const title = brief.title.trim() || "My Percfect Hero";
  const cast = brief.cast.trim() || "one original lead with a consistent costume";

  if (brief.kind === "small") {
    return [
      "Edit the attached comic page. Change ONLY this:",
      brief.note?.trim() || "a small costume detail",
      "Keep the same panels, poses, background, framing, and costumes except for that one change.",
      `Preserve this art style: ${style}.`,
      "Do not add a title, captions, or readable letters.",
      SAFETY,
    ].join(" ");
  }

  if (brief.kind === "cover" || brief.page === 0) {
    return [
      `Comic book COVER for "${title}". This is a single full-bleed splash, not a panel grid, not an interior page.`,
      `Art style: ${style}.`,
      `Characters, keep their faces and costumes exactly like this description: ${cast}.`,
      `What the cover shows: ${brief.beat.trim() || title}.`,
      "No title lettering, no logos, no captions. Leave the top third clear of faces and action so a title can sit there later.",
      "If a character photo is attached, match that face and costume. Do not copy its background or pose.",
      SAFETY,
    ]
      .filter(Boolean)
      .join(" ");
  }

  const act = brief.page <= 3 ? "beginning" : brief.page <= 6 ? "middle" : "ending";
  const lines = [
    `Comic INTERIOR page ${brief.page} of 9, the ${act} of "${title}".`,
    "Draw a NEW page with 3 to 5 panels and a new layout.",
    `Art style: ${style}.`,
    `Characters on this page, same faces and costumes every panel: ${cast}.`,
    `What happens on this page only: ${brief.beat.trim()}.`,
    "If character photos are attached after the previous page, match those faces. Do not paste the photos into a panel.",
  ];
  if (brief.actSummary?.trim()) {
    lines.push(`Act context, do not redraw earlier events: ${brief.actSummary.trim()}`);
  }
  if (brief.hasPrevPage) {
    lines.push(
      brief.page === 1
        ? "The attached reference is the COVER. Do not make another cover. Use it only to match the character's face, costume, and art style."
        : "The first attached reference is the PREVIOUS page. Match the characters and the art style. Do not copy its panels or redraw that same moment.",
    );
  }
  lines.push("Empty speech balloons only. No readable words, logos, or watermarks.", SAFETY);
  return lines.join(" ");
}
