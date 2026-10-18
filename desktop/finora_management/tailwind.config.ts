import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: token("ink"), soft: token("ink-soft"), faint: token("ink-faint") },
        surface: { DEFAULT: token("surface"), sunken: token("surface-sunken") },
        line: token("line"),
        maroon: { DEFAULT: token("maroon"), soft: token("maroon-soft") },
        violet: { DEFAULT: token("violet"), soft: token("violet-soft"), deep: token("violet-deep") },
        azure: { DEFAULT: token("azure"), soft: token("azure-soft") },
        cyan: { DEFAULT: token("cyan"), soft: token("cyan-soft") },
        success: { DEFAULT: token("success"), soft: token("success-soft") },
        warning: { DEFAULT: token("warning"), soft: token("warning-soft") },
        danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans Arabic"', '"Inter Variable"', "system-ui", "sans-serif"],
        num: ['"Inter Variable"', '"IBM Plex Sans Arabic"', "system-ui", "sans-serif"],
      },
      borderRadius: { window: "26px", panel: "20px", control: "14px" },
      boxShadow: {
        glass: "0 1px 0 rgb(255 255 255 / 0.9) inset, 0 18px 50px -24px rgb(76 54 140 / 0.28), 0 2px 8px -4px rgb(76 54 140 / 0.12)",
        float: "0 24px 60px -28px rgb(60 40 120 / 0.35), 0 4px 14px -6px rgb(60 40 120 / 0.16)",
        control: "0 1px 0 rgb(255 255 255 / 0.9) inset, 0 4px 12px -8px rgb(76 54 140 / 0.3)",
      },
    },
  },
  plugins: [],
} satisfies Config;
