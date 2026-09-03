/**
 * Tailwind config for untangle's institutional landing page.
 * Google-Material-clean tokens, brand blue = #2b5edb (consistent with the app shell).
 * Dev-only: the CSS it produces is compiled once (tools/tailwind/build.sh) and
 * committed to webapp/static/landing.css, so the running app never needs Node.
 */
module.exports = {
  content: [require("path").join(__dirname, "../../webapp/templates/landing.html")],
  theme: {
    extend: {
      colors: {
        primary: "#2b5edb",
        "primary-hover": "#1e49b8",
        "primary-tint": "#e8f0fe",
        secondary: "#137333",
        "secondary-tint": "#e6f4ea",
        tertiary: "#b06000",
        "tertiary-tint": "#fef7e0",
        error: "#c5221f",
        "error-tint": "#fce8e6",
        surface: "#f8f9fa",
        "surface-card": "#ffffff",
        border: "#e2e8f0",
        "border-light": "#edf2f7",
        "on-surface": "#202124",
        "on-surface-variant": "#5f6368",
        "on-surface-subtle": "#80868b",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        display: ["Hanken Grotesk", "Inter", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
};
