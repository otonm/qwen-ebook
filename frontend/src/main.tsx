import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"

// Light mode only, no theme toggle (UI-SPEC Design System / this plan's
// prohibitions) — the scaffolded ThemeProvider ships a global "d" keydown
// toggle and a "system" default that can apply `.dark` unprompted; neither
// is wanted here, so it's intentionally not wired in.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
