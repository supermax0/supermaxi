import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({ ...base, testMatch: "project-map.spec.ts", use: { ...base.use, channel: "chrome", launchOptions: { args: ["--disable-gpu"] } } });
