export const GENRES = [
  "Superhero",
  "Adventure",
  "Mystery",
  "Sci-fi",
  "Fantasy",
  "Horror",
  "Drama",
  "Comedy",
  "Western",
  "Crime",
  "Romance",
  "Slice of life",
] as const;

export type StyleId =
  | "classic"
  | "anime"
  | "realistic"
  | "gta5"
  | "watercolor"
  | "noir"
  | "pixel"
  | "cel"
  | "oil"
  | "cyberpunk"
  | "retro90s"
  | "sketch"
  | "two-d"
  | "three-d";

export type ComicStyle = { id: StyleId; label: string; blurb: string; prompt: string };

export const STYLES: ComicStyle[] = [
  { id: "classic", label: "Classic comic", blurb: "Bold inks, American newsstand", prompt: "classic American comic book print, bold black ink outlines, flat colored fills, Ben-Day dots" },
  { id: "anime", label: "Anime", blurb: "Sharp linework, cel color", prompt: "modern anime manga page, clean inked linework, cel shading, cinematic eyes, screentones" },
  { id: "realistic", label: "Realistic", blurb: "Painted faces, photographic light", prompt: "realistic painted comic page, cinematic lighting, detailed fabric and skin" },
  { id: "gta5", label: "GTA 5", blurb: "Saturated satirical game stills", prompt: "satirical open-world game still as a comic page, saturated color, bold outline" },
  { id: "watercolor", label: "Watercolor", blurb: "Wet pigment, soft edges", prompt: "watercolor comic page, wet pigment blooms, paper grain, soft edges" },
  { id: "noir", label: "Noir", blurb: "Black, white, and one red", prompt: "black-and-white noir comic, heavy ink shadows, one crimson accent" },
  { id: "pixel", label: "Pixel art", blurb: "Chunky pixels, 16-bit panels", prompt: "16-bit pixel art comic page, chunky pixels, limited palette" },
  { id: "cel", label: "Cel-shaded", blurb: "Cartoon game lighting", prompt: "cel-shaded game-comic page, crisp cartoon lighting, clean color holds" },
  { id: "oil", label: "Oil painting", blurb: "Thick impasto, gallery light", prompt: "oil painting comic page, thick impasto, gallery light" },
  { id: "cyberpunk", label: "Cyberpunk neon", blurb: "Rain, magenta, cyan", prompt: "cyberpunk neon comic page, rain, magenta and cyan rim light" },
  { id: "retro90s", label: "Retro 90s", blurb: "Foil-era, extreme poses", prompt: "1990s foil-era superhero comic, extreme poses, bold ink, saturated fills" },
  { id: "sketch", label: "Pencil sketch", blurb: "Graphite, construction lines", prompt: "graphite pencil comic page, construction lines" },
  { id: "two-d", label: "2D graphics", blurb: "Flat vector shapes", prompt: "flat 2D graphic comic page, vector shapes, limited palette" },
  { id: "three-d", label: "3D graphics", blurb: "Rendered models, studio CG", prompt: "3D rendered comic page, studio CGI characters, sequential panels" },
];

export function styleById(id: string): ComicStyle {
  return STYLES.find((s) => s.id === id) ?? STYLES[0];
}

export const SAFETY =
  "All-ages. No nudity, no sexual content, no gore. Original characters only. No readable letters, logos, watermarks, or barcodes.";
