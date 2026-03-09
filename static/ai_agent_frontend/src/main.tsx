import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./modules/App";
import "./style.css";

const rootElement = document.getElementById("ai-agent-root");

if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

