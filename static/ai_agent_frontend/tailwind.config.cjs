module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b1220",
        canvas: "#1e293b",
        card: "#111827",
        border: "#334155",
        text: "#e5e7eb",
        accent: "#22c55e",
        "accent-light": "#4ade80",
        "node-bg": "#0f172a",
        "edge": "#38bdf8",
        "node-start": "#22c55e",
        "node-ai": "#a855f7",
        "node-image": "#ec4899",
        "node-caption": "#3b82f6",
        "node-publisher": "#f97316",
        "node-scheduler": "#06b6d4",
        "node-listener": "#eab308",
        "node-reply": "#ef4444",
        "node-end": "#6b7280",
      },
      borderRadius: { "workflow": "12px" },
      boxShadow: {
        "soft": "0 4px 14px rgba(0,0,0,0.25)",
        "card": "0 4px 20px rgba(0,0,0,0.3)",
      },
    },
  },
  plugins: [],
};

