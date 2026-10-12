// Categorical palette in fixed order (validated for colour-blind separation of adjacent slots).
// Assign hues in this order; a series keeps its colour when filters change.
export const PALETTE = [
  "#2a78d6", // 1 blue
  "#eb6834", // 2 orange
  "#1baf7a", // 3 aqua
  "#eda100", // 4 yellow
  "#e87ba4", // 5 magenta
  "#008300", // 6 green
  "#4a3aa7", // 7 violet
  "#e34948", // 8 red
];

// Named series colours, for charts that pair a main measure with a second one.
export const SERIES = {
  blue: PALETTE[0],
  blueLight: "#86b6ef",
  orange: PALETTE[1],
  aqua: PALETTE[2],
  yellow: PALETTE[3],
  violet: PALETTE[6],
  red: PALETTE[7],
  prior: "#b5b2a9",
};

// Fixed status colours (never reused for an ordinary series)
export const STATUS_COLORS: Record<string, string> = {
  Delivered: "#0ca30c",
  Processing: "#2a78d6",
  Returned: "#eda100",
  Cancelled: "#d03b3b",
};

export function colorFor(key: string, i: number): string {
  return STATUS_COLORS[key] ?? PALETTE[i % PALETTE.length];
}

export const POSITIVE = "#0b7f0b";
export const NEGATIVE = "#c43535";
export const NEUTRAL = "#73706a";

// Chart chrome
export const INK = "#1b1a18";
export const INK_2 = "#57554f";
export const MUTED = "#8a877f";
export const GRID_LINE = "#ebe9e3";
export const BASELINE = "#cfccc4";
export const FONT = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif";
