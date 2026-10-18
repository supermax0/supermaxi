import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no layout/scrolling implementation. Product editor focus effects
// use the browser's Element.scrollTo API after rendering.
if (!Element.prototype.scrollTo) {
  Object.defineProperty(Element.prototype, "scrollTo", { configurable: true, value: vi.fn() });
}

// Whole-app renders run in parallel workers; 1 s is too tight for findBy* under load.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
});
