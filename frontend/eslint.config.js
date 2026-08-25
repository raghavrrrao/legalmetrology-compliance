/**
 * ESLint flat config.
 *
 * Six people write JavaScript in this repository. The point of this file is to
 * settle the arguments that are not worth having (unused variables, hook
 * dependencies) so review time goes to the ones that are.
 *
 * Deliberately not included: a formatter (Prettier) or stylistic rules about
 * quotes and semicolons. Those generate churn and diff noise without catching
 * bugs. Everything configured below catches something that can actually break.
 *
 * Run with `npm run lint`, or `npm run lint:fix` to apply safe fixes.
 */

import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
  {
    // Build output and dependencies are not ours to lint.
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },

  js.configs.recommended,

  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: {
        ...globals.browser,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: {
      react: { version: 'detect' },
    },
    plugins: {
      react,
      'react-hooks': reactHooks,
    },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...react.configs.flat['jsx-runtime'].rules,

      // --- hooks: these catch real, hard-to-debug bugs -------------------
      'react-hooks/rules-of-hooks': 'error',
      // A missing dependency produces a stale closure - the component keeps
      // reading the value from the render it was created in. It is the single
      // most common React bug and it never throws, so it is an error here.
      'react-hooks/exhaustive-deps': 'error',

      // --- correctness ---------------------------------------------------
      // Allow deliberately-ignored args prefixed with _, which is the usual
      // way to say "this parameter exists but I do not need it".
      'no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      eqeqeq: ['error', 'smart'],
      'no-var': 'error',
      'prefer-const': 'error',
      // console.error/warn are legitimate; a stray console.log is debug
      // residue that should not reach main.
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // PropTypes are off: this project uses plain JSX with no runtime type
      // checking, and turning them on would demand boilerplate on every
      // component for no enforcement anybody relies on.
      'react/prop-types': 'off',
    },
  },

  {
    // Test files run in Node with Vitest globals, not only in a browser.
    files: ['**/*.test.{js,jsx}', 'src/test/**'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.vitest,
        fetch: 'writable', // stubbed via vi.stubGlobal in several suites
      },
    },
  },

  {
    // Config files are Node modules, not browser code.
    files: ['*.config.js', 'eslint.config.js'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
];
