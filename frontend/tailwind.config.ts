import type { Config } from "tailwindcss";

// Warm neutral greys replace Tailwind's cool slate everywhere (all pages use `slate-*`).
// `brand` is the blue ramp of the chart palette, so UI accents and data share one hue.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["IBM Plex Sans", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "Consolas", "monospace"],
      },
      colors: {
        slate: {
          50: "#f7f6f3",
          100: "#efeee9",
          200: "#e4e2dc",
          300: "#cfccc4",
          400: "#9d9a91",
          500: "#73706a",
          600: "#57554f",
          700: "#42403b",
          800: "#2a2926",
          900: "#1b1a18",
          950: "#121110",
        },
        brand: {
          50: "#eef4fc",
          100: "#dbe8fa",
          200: "#b7d3f6",
          300: "#86b6ef",
          400: "#5598e7",
          500: "#2a78d6",
          600: "#256abf",
          700: "#1c5cab",
          800: "#184f95",
          900: "#0d366b",
        },
        status: {
          delivered: "#0ca30c",
          processing: "#2a78d6",
          returned: "#eda100",
          cancelled: "#d03b3b",
        },
      },
      borderRadius: {
        DEFAULT: "4px",
      },
      boxShadow: {
        card: "0 1px 0 rgba(27,26,24,.04)",
        pop: "0 1px 2px rgba(27,26,24,.06), 0 8px 24px -6px rgba(27,26,24,.16)",
      },
    },
  },
  plugins: [],
} satisfies Config;
