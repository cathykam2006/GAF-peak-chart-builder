# Browser version of the app (GitHub Pages)

This branch holds one page, `index.html`, that runs the GAF Peak Chart Builder
entirely in the visitor's browser with [stlite](https://github.com/whitphx/stlite).
There is no server, so it never goes to sleep, and uploaded filings never leave
the visitor's device. The Streamlit Community Cloud app keeps running from `main`.

- The page loads the app's `.py` files from the `main` branch each time it
  opens, so changes pushed to `main` appear here automatically.
- PDFs are read with pypdfium2's browser build, the same engine the Streamlit
  app uses.
- If the app gains a new `.py` file, add its name to `FILES` in `index.html`
  (and in `404.html`, a copy that lets links to the second page reload).
