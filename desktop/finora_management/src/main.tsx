import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import "@fontsource-variable/inter";
import "./theme/index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";

// Decode every font face up front: the first window otherwise pays for loading
// the bold Arabic faces (and a relayout) in the middle of its opening morph.
if ("fonts" in document) {
  const faces = ["400", "500", "600", "700"].flatMap((weight) => [
    `${weight} 16px "IBM Plex Sans Arabic"`,
    `${weight} 16px "Inter Variable"`,
  ]);
  void Promise.allSettled(faces.map((face) => document.fonts.load(face, "أبجد 0123")));
}

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
