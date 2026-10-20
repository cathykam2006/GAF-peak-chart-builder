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
