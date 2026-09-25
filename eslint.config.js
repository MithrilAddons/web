import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["frontend/dist/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["frontend/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
);
