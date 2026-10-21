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

## How it works

1. **Drop filings**: drag and drop PDF or Excel schedules. The company is
   detected from the file name (editable). Only the R-3 page/sheet is used,
   based on the line that names the customer class.
2. **Sections identified**: every R-3 scenario becomes a separate section that
   shows what it compares:
   - the page's "compared to" line
   - *Compared from*: the current-rates header (e.g. LDAF / CGA effective dates)
   - *Compared to*: the proposed-rates header
   - variant subtitles, change lines, footnotes, and the source row of every value
3. **Parts**: each scenario goes into its own Part (chart). Each Part has an
   editable peak grid, the LDAF table, an Average row, comparison-basis columns,
   and its own CSV download. All Parts can also be exported in one CSV.

## What is pulled

| Field | Source on the R-3 schedule |
|---|---|
| Peak average monthly usage | Peak-period therms ÷ 6 |
| Prior / proposed peak GAF | Cost of Gas Adjustment (CGA) row, current vs proposed block (usage-weighted if it varies Nov–Apr) |
| Prior / proposed monthly bill | Peak-period bill total ÷ 6 (plain / without-discount rows) |
| Current / proposed LDAF | Total LDAC row |

Calculated: % change in GAF, bill change, % bill change, change due to GAF only
(ΔGAF × usage), LDAF total-bill change (usage × ΔLDAF).

Entered by hand: bill change using prior LDAFs, reduced and off-peak LDAFs.

## Mass.gov rate page (second page in the sidebar)

Builds the next section of
[Information on Gas Supply and Delivery Charges](https://www.mass.gov/info-details/information-on-gas-supply-and-delivery-charges).

1. **Pull the posted rates**: read live from mass.gov. If the site blocks the
   request, drop a saved copy of the page (.html) or paste text copied from it.
   Any posted section can be viewed or exported as CSV, including the full history.
   All posted revisions are listed newest first, grouped by season, with
   links to their sections on the page. Any two revisions can be compared
   (every GAF/LDAF change, and whether the page flagged it REVISED).
2. **Start the next revision**: pick a base section. The next title and
   effective dates are suggested, e.g. after *Off-Peak/Summer 2026 Rates
   Revision 3 (Effective 10/1/26 through 10/31/26)* it suggests *Peak/Winter
   2026-2027 Rates (Effective 11/1/26 through 11/30/26)*. All of these can be edited.
3. **Fill in new values**:
   - from a Peak chart Part: the proposed R-3 GAF and LDAF go into each
     company's residential heating (or All Residential) row. The new GAF can also
     be applied to other classes that shared the old residential heating GAF.
   - or by editing each company's table and notes directly.
   Companies whose values changed are marked **REVISED** automatically (can be overridden).
4. **Export** in the page's format: plain text, HTML for the web editor, or CSV,
   plus the updated revision list with the new section on top (text or HTML links).
