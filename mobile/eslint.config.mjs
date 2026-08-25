import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import importPlugin from "eslint-plugin-import";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Lint rules for the Expo app.
 *
 * The web app extends `eslint-config-next`, which brings its own React and TypeScript
 * setup along with rules about the Next router and image component — none of which apply
 * here. This is the same intent assembled from the underlying plugins instead.
 *
 * Type-aware linting is on. It costs a slower run, and it is the only way to catch the
 * class of bug that matters most in this codebase: a floating promise. Every write in the
 * offline path is async, and an unawaited one is a set that silently never reaches
 * SQLite.
 */
export default defineConfig([
  globalIgnores([
    "node_modules/**",
    ".expo/**",
    "dist/**",
    "android/**",
    "ios/**",
    "expo-env.d.ts",
  ]),

  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,

  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        console: "readonly",
        crypto: "readonly",
        fetch: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        queueMicrotask: "readonly",
        ResizeObserver: "readonly",
        __DEV__: "readonly",
      },
    },
    plugins: { react, "react-hooks": reactHooks, import: importPlugin },
    settings: { react: { version: "detect" } },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,

      // React Native has no JSX transform import requirement, and components are typed
      // by TypeScript rather than by prop-types.
      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",

      // The rule this config exists for. An unawaited write in the offline path is a set
      // that never reaches SQLite, and the user finds out days later when their history
      // has a hole in it. `void` is the explicit opt-out and is used deliberately
      // throughout the workout screen.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": [
        "error",
        // A `() => Promise<void>` handler is idiomatic in React Native and safe; the
        // dangerous case is a promise where a boolean is expected.
        { checksVoidReturn: false },
      ],

      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      // Import order, so a growing feature folder does not turn into a scramble.
      "import/order": [
        "warn",
        {
          groups: [["builtin", "external"], "internal", ["parent", "sibling", "index"]],
          pathGroups: [{ pattern: "@/**", group: "internal" }],
          pathGroupsExcludedImportTypes: ["builtin"],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
    },
  },

  {
    // Config files are not part of the app's tsconfig, so the type-aware rules have no
    // program to consult. Linted without type information rather than skipped, which
    // still catches syntax and unused imports.
    files: ["*.config.mjs", "*.config.mts", "*.config.js"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { parserOptions: { projectService: false, project: null } },
  },

  {
    // Tests reach into internals and assert on shapes the compiler cannot narrow, so
    // the any-related rules would fire constantly for no benefit.
    files: ["**/*.test.ts", "**/*.test.tsx"],
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
]);
