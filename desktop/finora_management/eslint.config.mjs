import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "dist-electron", "node_modules", "test-results", "playwright-report", "*.cjs"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.electron.json", "./tsconfig.e2e.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "no-empty": ["error", { allowEmptyCatch: false }],
      "no-warning-comments": ["error", { terms: ["todo", "fixme"], location: "start" }],
    },
  },
  {
    files: ["electron/**/*.ts", "scripts/**/*.mjs", "e2e/**/*.ts", "*.config.{ts,mjs}"],
    languageOptions: { globals: { ...globals.node } },
  },
);
