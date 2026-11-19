# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## Structure and tests

- `src/api/`: one module per backend app, calling it through `client.js`.
- `src/offline/`: the till's offline copy and outbox. `catalog.js` and
  `snapshotMerge.js` are pure (no browser APIs). `till.js`, `outbox.js` and
  `db.js` do the storing and syncing.
- `src/screens/`: one file per screen. A screen's parts live in a folder named
  after it (`pos/`, `settings/`, `analytics/`). Rules a screen applies go in a
  plain `.js` module beside it (for example `pos/cart.js`), not in the
  component, so they can be tested.
- `src/components/ds/`: the design system.

`npm test` runs the `*.test.js` files with Node's built-in test runner, with
nothing to install. Tests cover the till's offline logic (searching, the ways
a product can be sold and the stock left, merging a fresh snapshot) and the
cart (stock limits, totals and VAT, discount approval, credit limits, the
sale record that is sent). Test only modules that don't touch the browser;
`offline/fixtures.js` has a small till snapshot to test against.

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and Oxlint's TypeScript related rules in your project.
