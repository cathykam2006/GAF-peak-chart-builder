# GAF Peak Chart Builder (R-3 Residential Heating)

Created by Cathy Kam.

Streamlit app that pulls R-3 (Residential Heating) peak data from gas companies'
typical-bill schedules (e.g. Attachment DPU-LDC-2-3(d)(3)) into the peak GAF
chart layout, and exports it as CSV.

## Run

```bash
pip install -r requirements.txt
streamlit run gaf_peak_app.py
```

## How it works (Peak chart page)

1. **Drop filings**: drag and drop the companies' CGAC / LDAC filings or
   typical-bill schedules (PDF or Excel). The company is detected (editable)
   and every R-3 typical-bill page is found.
2. **Identify sections** — **Latest GAF / LDAF and scenario comparison**: an
   overview per company of the latest proposed rates and where they come from,
   plus every scenario the company filed side by side (see below).
3. **Peak chart — latest proposed rates**: one chart, filled automatically:
   the peak chart, the Residential-Heating LDAF table and the Alternative
   Residential LDAF table. Every cell can be edited. Under each table,
   *Where each number comes from* names the file, section, page and basis of
   each value (or the formula, or "typed in by hand").
4. **Export**: one CSV with the three tables followed by the source of every value.

## Mass.gov rate page (second page in the sidebar)

Pulls GAF/LDAF rates from PDFs and exports them as an Excel table laid out
like [Information on Gas Supply and Delivery Charges](https://www.mass.gov/info-details/information-on-gas-supply-and-delivery-charges),
ready to be transferred to the webpage.

1. **Drop PDFs**: company rate filings. The app reads:
   - typical-bill schedules (e.g. Attachment DPU-LDC-2-3(d)(3)): proposed CGA
     (GAF) and Total LDAC (LDAF) for each rate class, for the effective month
   - rate tables listing GAF and/or LDAF by rate class (R-1, G-41, T-54, ...)
   - optionally a PDF of the mass.gov page itself (Print → Save as PDF), which
     updates the starting layout (companies, notes, rate classes, posted values)
2. **New section**: title and effective dates are suggested from the last posted
   section (e.g. *Peak/Winter 2026-2027 Rates (Effective 11/1/26 through 11/30/26)*).
3. **Review**: pulled rates are shown per file (editable, can be left out);
   each is matched to the page's rate-class rows. A changed GAF can also be
   applied to classes that shared the same posted GAF (e.g. EGMA G-40 to G-43
   follow R-3). Values not in any filing are carried forward and **highlighted
   in yellow** (preview and Excel) so they are checked before posting.
   Companies that changed are marked REVISED automatically.
4. **Export Excel**: sheet *Webpage layout* (section title, company headings with
   REVISED, notes, Rate Class / Billing Unit / GAF / LDAF tables) and sheet
   *Table* (same data as one flat table, with the source of each value:
   from filing, shared GAF, edited by hand, or carried forward).

## Large filings and many files

- PDFs are read with pypdfium2 (a 250-page filing takes about 1 second) and
  cached by file content, so each file is read once per session, not on every click.
- Only pages that mention CGA / GAF / LDAC / LDAF are parsed; invoices, letters
  and workpapers are skipped.
- Upload limit is raised to 1 GB per file (`.streamlit/config.toml`).
- A progress bar shows which file is being read.
- On the Mass.gov page, a filing can hold several values for one rate class (several
  scenario sections, current vs proposed). Priority: summary table with classes as
  columns (e.g. Form IIA) > rate table > typical-bill schedule that proposes the rate
  > other schedules. Other values found are listed beside each class. When several
  files cover the same company they are combined the same way; hand edits win.

## Latest rates across several filings (Peak chart page)

After **Identify sections**, step 2 shows, for each company:

- each file's type (CGAC / LDAC), Revised flag and filing date (taken from a
  "Filed:" line, or from another filing's reference such as
  "(LDAC)Revised filed on August 27, 2026"), plus any R-3 values in a summary table (Form IIA);
- the **latest proposed GAF and LDAF**: GAF from the cost-of-gas (CGAC) filing,
  LDAF from the LDAC filing, among scenarios that actually propose the rate,
  then the most recently filed and Revised documents, summary tables over
  typical-bill pages. Other proposed values are listed so they can be checked;
- the supporting values: average prior peak GAF (basis "CGA is average rate"),
  current peak LDAF (basis "LDAF effective November 1"), off-peak LDAF, and the
  bills from the scenario where only the GAF and LDAF change;
- **every scenario the company filed** side by side (basis, filing date, GAF, peak
  and off-peak LDAF, bill), flagged where it differs from the latest rate.

The chart in step 3 is filled from these values automatically, including the
**Alternative Residential LDAF** table (from illustrative / re-allocation
scenarios). Details of every scenario section are available for reference.
