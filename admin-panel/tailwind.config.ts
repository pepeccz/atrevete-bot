import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // ── shadcn base tokens (unchanged) ──────────────────────────────────
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
        surface: {
          DEFAULT: "hsl(var(--surface))",
          elevated: "hsl(var(--surface-elevated))",
          hover: "hsl(var(--surface-hover))",
          muted: "hsl(var(--surface-muted))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        info: {
          DEFAULT: "hsl(var(--info))",
          foreground: "hsl(var(--info-foreground))",
        },
        danger: {
          DEFAULT: "hsl(var(--danger))",
          foreground: "hsl(var(--danger-foreground))",
        },
        // ── Handoff design tokens (new) ──────────────────────────────────────
        ink: {
          DEFAULT: "hsl(var(--ink))",
          soft:    "hsl(var(--ink-soft))",
          mute:    "hsl(var(--ink-mute))",
          faint:   "hsl(var(--ink-faint))",
        },
        gold: {
          DEFAULT: "hsl(var(--gold))",
          dark:    "hsl(var(--gold-dark))",
          soft:    "hsl(var(--gold-soft))",
          line:    "hsl(var(--gold-line))",
        },
        line: {
          DEFAULT: "hsl(var(--line))",
          soft:    "hsl(var(--line-soft))",
        },
        status: {
          confirm:      "hsl(var(--status-confirm))",
          "confirm-bg": "hsl(var(--status-confirm-bg))",
          pending:      "hsl(var(--status-pending))",
          "pending-fg": "hsl(var(--status-pending-fg))",
          "pending-bg": "hsl(var(--status-pending-bg))",
          cancel:       "hsl(var(--status-cancel))",
          "cancel-bg":  "hsl(var(--status-cancel-bg))",
          done:         "hsl(var(--status-done))",
          "done-bg":    "hsl(var(--status-done-bg))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        // ── Handoff radii ─────────────────────────────────────────────────
        "card-lg": "14px",   // large cards
        "card-sm": "10px",   // small cards / appointment chips
        btn:       "10px",   // buttons & inputs
        pill:      "9999px", // round chips
      },
      fontFamily: {
        // ── Handoff fonts ─────────────────────────────────────────────────
        "serif-display": ["var(--font-serif-display)", "Georgia", "serif"],
        jakarta:         ["var(--font-jakarta)", "system-ui", "sans-serif"],
        body:            ["var(--font-jakarta)", "system-ui", "sans-serif"],
        // Backward compat: font-heading → jakarta (was Playfair)
        heading:         ["var(--font-jakarta)", "system-ui", "sans-serif"],
        // serif alias for wordmark (DM Serif Display)
        serif:           ["var(--font-serif-display)", "Georgia", "serif"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
