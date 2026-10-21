"""
GAF Peak Chart Builder  (R-3 Residential Heating)
Created by Cathy Kam
-------------------------------------------------
1. Drag and drop each company's typical-bill schedules (e.g. Attachment
   DPU-LDC-2-3(d)(3)), PDF or Excel.
2. Every R-3 section in every file is identified: page title, what the
   "current" block is based on, what the "proposed" block is based on, and
   which bill lines are compared.  A file with several scenarios (deferral /
   no deferral, 50%/75% options, LDAF-reduction variants ...) yields one
   section per scenario.
3. Sections are assigned to Parts.  Each Part is its own chart laid out like
   the "26-27 PEAK 11-1-26" sheet, editable, with its own CSV export.

Run:   streamlit run gaf_peak_app.py
Needs: streamlit pandas pdfplumber openpyxl
"""

import io
import re

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Chart layout (mirrors the Excel sheet)
# ---------------------------------------------------------------------------
COMPANIES = [  # (row name, is_group_header, keywords for auto-detection)
    ("Berkshire Gas", False, ["berkshire"]),
    ("EGMA", False, ["egma", "eversource gas company of massachusetts"]),
    ("Liberty Utilities", True, []),
    ("Fall River/North Attleboro", False, ["fall river", "north attleboro"]),
    ("Blackstone", False, ["blackstone"]),
    ("National Grid", True, []),
    ("Boston Gas", False, ["boston gas"]),
    ("former Colonial Gas", False, ["colonial"]),
    ("NSTAR Gas", False, ["nstar"]),
    ("Unitil (Fitchburg)", False, ["fitchburg", "unitil"]),
]
DATA_COMPANIES = [c for c, hdr, _ in COMPANIES if not hdr]
PEAK_MONTHS = ["nov", "dec", "jan", "feb", "mar", "apr"]

PEAK_INPUTS = ["prior_gaf", "prop_gaf", "usage", "prior_bill", "prop_bill",
               "chg_old_ldaf"]
LDAF_INPUTS = ["cur_ldaf", "reduced_ldaf", "offpeak_ldaf", "prop_ldaf",
               "prior_winter_bill", "prop_winter_bill"]
PEAK_ORDER = ["prior_gaf", "prop_gaf", "pct_gaf", "usage", "prior_bill",
              "prop_bill", "chg_bill", "pct_bill", "chg_gaf_only", "chg_old_ldaf"]
LDAF_ORDER = ["cur_ldaf", "reduced_ldaf", "offpeak_ldaf", "prop_ldaf", "pct_ldaf",
              "prior_winter_bill", "prop_winter_bill", "chg_total_bill"]


def peak_columns(prior, proposed, ldaf_date):
    return {
        "prior_gaf": f"Average {prior} Peak GAF",
        "prop_gaf": f"Proposed {proposed} Peak GAF",
        "pct_gaf": "Percent Change in GAF",
        "usage": "Peak Average Monthly Usage (therms)",
        "prior_bill": f"Average {prior} Peak Monthly Bill",
        "prop_bill": f"Proposed {proposed} Peak Monthly Bill",
        "chg_bill": "Change in  Bill Average GAF/LDAF",
        "pct_bill": "% Change in Monthly Bill",
        "chg_gaf_only": "Change in Monthly Bill due to GAF only",
        "chg_old_ldaf": f"Bill Change using {ldaf_date} LDAFs",
    }


def ldaf_columns(prior_short, proposed_short, ldaf_date):
    return {
        "cur_ldaf": f" {prior_short} LDAF ({ldaf_date})",
        "reduced_ldaf": "Reduced LDAFs (Feb/Mar/Apr)",
        "offpeak_ldaf": "Revised LDAF (Off-Peak)",
        "prop_ldaf": f"Proposed {proposed_short} LDAF",
        "pct_ldaf": f"% Change from {ldaf_date} LDAF",
        "prior_winter_bill": f" {prior_short} Winter Bill",
        "prop_winter_bill": f"Projected {proposed_short} Winter Bill",
        "chg_total_bill": "Change in Total Bill",
    }


# ---------------------------------------------------------------------------
# Reading files -> list of (page label, lines)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=64)
def read_pages(name, data):
    lname = name.lower()
    pages = []
    if lname.endswith(".pdf"):
        from pdf_text import pdf_pages
        pages = [(f"p.{i}", lines) for i, lines in enumerate(pdf_pages(data), 1)]
    elif lname.endswith((".xlsx", ".xlsm", ".xls")):
        for sname, df in pd.read_excel(io.BytesIO(data), sheet_name=None,
                                       header=None).items():
            lines = []
            for row in df.itertuples(index=False):
                cells = [repr(v) if isinstance(v, float) else str(v)
                         for v in row if not pd.isna(v)]
                if cells:
                    lines.append(" ".join(cells))
            pages.append((f"sheet '{sname}'", lines))
    elif lname.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data), header=None)
        pages.append(("csv", [" ".join(str(v) for v in r if pd.notna(v))
                              for r in df.itertuples(index=False)]))
    else:
        pages.append(("text", data.decode("utf-8", errors="ignore").splitlines()))
    return pages


def guess_company(filename, pages):
    for hay in (filename.lower(),
                " ".join(" ".join(l[:8]) for _, l in pages[:2]).lower()):
        for comp, hdr, kws in COMPANIES:
            if not hdr and any(k in hay for k in kws):
                return comp
    return None


def rate_class_line(lines):
    """The line that names the customer class, e.g. 'Typical Residential
    Heating (R-3)'.  Other lines may mention R-3 in passing (e.g. 'LDAF
    re-allocation for Rate R-3 only'), so only this line decides."""
    for line in lines[:15]:
        low = line.lower()
        if re.search(r"typical|residential", low) and \
                re.search(r"\(?\b(r|rate)[- ]?\d\b\)?|heating", low):
            return line
    return ""


def is_r3_page(lines):
    cls = rate_class_line(lines).lower()
    if not cls:
        return False
    if re.search(r"low income|non-heating", cls):
        return False
    m = re.search(r"\br[- ]?(\d)\b", cls)
    ok = (m.group(1) == "3") if m else "residential heating" in cls
    # must be a typical-bill schedule (monthly columns), not e.g. a tariff page
    return ok and any(len(re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                                     l.lower())) >= 10 for l in lines[:40])


# ---------------------------------------------------------------------------
# Schedule parser
# ---------------------------------------------------------------------------
NUM_TOKEN = re.compile(r"^(\(\$?-?[\d,]*\.?\d+%?\)|-?\$?-?[\d,]*\.?\d+%?)$")


def to_float(tok):
    t = tok.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[()\$,%]", "", t)
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def split_row(line):
    """'34 Total LDAC $0.62 ... $103.66' -> ('Total LDAC', [0.62, ..., 103.66])"""
    toks = line.split()
    vals = []
    while toks and NUM_TOKEN.match(toks[-1]):
        vals.append(to_float(toks.pop()))
    vals.reverse()
    label = re.sub(r"^\d+\s*(?=[A-Za-z(])", "", " ".join(toks)).strip()
    if len(vals) > 15:            # a footnote marker like "(1)" got swept in
        vals = vals[-15:]
    return label, vals


def month_order(lines):
    for line in lines[:25]:
        found = re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                           line.lower())
        if len(found) >= 10:
            return found[:12]
    return ["nov", "dec", "jan", "feb", "mar", "apr",
            "may", "jun", "jul", "aug", "sep", "oct"]


def peak_value(vals, order, is_rate=False):
    """15 values = 12 months + Annual + Peak + Off-Peak -> Peak column.
    Otherwise sum the Nov–Apr months (or, for a rate, take November)."""
    if not is_rate and len(vals) >= 15:
        return vals[13]
    if len(vals) >= 12:
        months = [vals[order.index(m)] for m in PEAK_MONTHS if m in order]
        months = [m for m in months if m is not None]
        if not months:
            return None
        return months[0] if is_rate else sum(months)
    return None


GAF_RE = re.compile(r"cost of gas|\bcga\b|\bgaf\b|gas adjustment factor", re.I)
LDAF_RE = re.compile(r"total ldac|\bldaf\b|local distribution adjustment factor", re.I)
PROP_HDR = re.compile(r"^(proposed|illustrative|new|revised)\b|proposed/illustrative"
                      r"|proposed rates|illustrative rates", re.I)
CUR_HDR = re.compile(r"^(current|present|existing|approved)\b|rates in effect", re.I)
BILL_HDR = re.compile(r"bill impact|bill comparison", re.I)
CUR_BILL = re.compile(r"(current|present|existing|approved).*bill", re.I)
NEW_BILL = re.compile(r"(illustrative|proposed|new|revised).*bill", re.I)
ADMIN_TITLE = re.compile(r"d/b/a|d\.p\.u\.|attachment|^page \d|exhibit|schedule \w+$",
                         re.I)


def plain_bill(label):
    low = label.lower()
    return "without" in low or not re.search(r"with\b|discount|tier", low)


def parse_page(lines):
    """Split one R-3 page into its sections and build one scenario per
    Proposed block.

    Returns dict(title, current_hdrs, proposed_hdrs, bill_hdr, comparisons,
                 footnotes, scenarios=[{label, current_basis, proposed_basis,
                 values, sources, notes}])
    """
    order = month_order(lines)
    blocks = [{"kind": "current", "header": "(rates before any section header)",
               "rows": []}]
    title, footnotes, comparisons, bills = [], [], [], []
    usage_row, impact_rows = None, []
    seen_rows = False

    for line in lines:
        label, vals = split_row(line)
        low = label.lower()
        if len(vals) < 3:                                   # text / header line
            clean = re.sub(r"^\d+\s*(?=[A-Za-z(])", "", line).strip()
            lc = clean.lower()
            if not clean or not re.search(r"[A-Za-z]{2}", clean) \
                    or set(clean) <= set("-( )abcdefghijklmnop") \
                    or re.fullmatch(r"(total\s*)+", lc) \
                    or re.search(r"\bnov\b.*\bdec\b", lc):
                continue
            if re.match(r"^\(\d+\)", clean):
                footnotes.append(clean)
            elif seen_rows and PROP_HDR.search(lc) and "bill" not in lc:
                blocks.append({"kind": "proposed", "header": clean, "rows": []})
            elif seen_rows and CUR_HDR.search(lc) and "bill" not in lc:
                blocks.append({"kind": "current", "header": clean, "rows": []})
            elif BILL_HDR.search(lc):
                blocks.append({"kind": "bill", "header": clean, "rows": []})
            elif not seen_rows and CUR_HDR.match(lc):
                blocks[0]["header"] = clean
            elif not seen_rows and not clean.endswith(":") \
                    and not ADMIN_TITLE.search(clean):
                title.append(clean)
            continue

        seen_rows = True
        if usage_row is None and re.search(r"therm|usage|\buse\b", low) \
                and "$" not in line and len(vals) >= 12:
            usage_row = (label, vals)
            continue
        if low.startswith("change"):
            comparisons.append(label)
            continue
        if "average monthly impact" in low:
            impact_rows.append((label, vals))
            comparisons.append(label)
            continue
        if "bill" in low:
            bills.append((label, vals, len(blocks) - 1))
            continue
        blocks[-1]["rows"].append((label, vals))

    # -- common pieces --------------------------------------------------
    usage, pk_therms, usage_src = None, None, None
    if usage_row:
        pk_therms = peak_value(usage_row[1], order)
        if pk_therms:
            usage = r2(pk_therms / 6)
            usage_src = f"{usage_row[0]}: peak therms {pk_therms:g} ÷ 6"

    def find(rows, regex, exclude=r"recon|exogenous"):
        for label, vals in rows:
            if regex.search(label) and not re.search(exclude, label, re.I) \
                    and len(vals) >= 12:
                return label, vals
        return None

    def gaf_from(row, notes, tag):
        label, vals = row
        rate = peak_value(vals, order, is_rate=True)
        if len(vals) >= 15 and pk_therms:
            w = vals[13] / pk_therms
            if rate is None or abs(w - rate) > 0.0005:
                notes.append(f"{tag} GAF varies Nov–Apr; used usage-weighted {w:.4f}")
                rate = round(w, 4)
        return rate

    cur_bills = [b for b in bills if CUR_BILL.search(b[0]) and plain_bill(b[0])]
    new_bills = [b for b in bills if NEW_BILL.search(b[0]) and plain_bill(b[0])]
    other_bills = [b[0] for b in bills if not plain_bill(b[0])]

    prop_blocks = [i for i, b in enumerate(blocks) if b["kind"] == "proposed"]
    if not prop_blocks:  # no labelled proposed block: treat 2nd rate block as one
        rate_blocks = [i for i, b in enumerate(blocks) if b["kind"] != "bill"]
        prop_blocks = rate_blocks[1:2]

    scenarios = []
    for n, pi in enumerate(prop_blocks):
        ci = max([i for i in range(pi) if blocks[i]["kind"] == "current"],
                 default=0)
        cur, prop = blocks[ci], blocks[pi]
        if not prop["rows"]:          # e.g. a footer "Proposed Rates Effective ..." line
            continue
        vals, src, notes, extra = {}, {}, [], {}
        may = order.index("may") if "may" in order else None
        if usage is not None:
            vals["usage"], src["usage"] = usage, usage_src
        for key, blk, tag in (("prior_gaf", cur, "Current"),
                              ("prop_gaf", prop, "Proposed")):
            r = find(blk["rows"], GAF_RE)
            if r:
                vals[key] = gaf_from(r, notes, tag)
                src[key] = f"{tag} block → {r[0]}"
        for key, blk, tag in (("cur_ldaf", cur, "Current"),
                              ("prop_ldaf", prop, "Proposed")):
            r = find(blk["rows"], LDAF_RE)
            if r:
                vals[key] = peak_value(r[1], order, is_rate=True)
                src[key] = f"{tag} block → {r[0]}"
                if may is not None and len(r[1]) > may:
                    extra[key + "_offpeak"] = r[1][may]
        for key, blk in (("prior_gaf", cur), ("prop_gaf", prop)):
            r = find(blk["rows"], GAF_RE)
            if r and may is not None and len(r[1]) > may:
                extra[key + "_offpeak"] = r[1][may]
        if usage_row and len(usage_row[1]) >= 15:
            extra["usage_offpeak"] = r2(usage_row[1][14] / 6)
        # bills: pair the n-th proposed bill with the n-th scenario
        cb = cur_bills[min(n, len(cur_bills) - 1)] if cur_bills else None
        nb = None
        if new_bills:
            if len(new_bills) == len(prop_blocks):
                nb = new_bills[n]
            else:
                nb = new_bills[0]
                if len(prop_blocks) > 1:
                    notes.append("Bill rows could not be matched one-to-one to "
                                 "proposed blocks — check the bill figures")
        for key, wkey, b in (("prior_bill", "prior_winter_bill", cb),
                             ("prop_bill", "prop_winter_bill", nb)):
            if b:
                tot = peak_value(b[1], order)
                if tot is not None:
                    vals[key] = r2(tot / 6)
                    vals[wkey] = r2(tot)
                    src[key] = f"{b[0]}: peak-period total ${tot:,.2f} ÷ 6"
        if impact_rows and "prior_bill" in vals and "prop_bill" in vals:
            chk = impact_rows[min(n, len(impact_rows) - 1)][1]
            if len(chk) >= 2:
                calc = vals["prop_bill"] - vals["prior_bill"]
                if abs(chk[1] - calc) > 0.05:
                    notes.append(f"Schedule shows peak avg monthly impact "
                                 f"${chk[1]:,.2f}; bills give ${calc:,.2f}")
        if other_bills:
            notes.append("Also on page (not used): " + "; ".join(other_bills))
        compared = [t for t in title if re.search(r"compar|\bvs\.?\b|versus", t, re.I)]
        scenarios.append({
            "compared_line": " / ".join(compared),
            "current_basis": cur["header"],
            "proposed_basis": prop["header"],
            "values": vals, "sources": src, "notes": notes, "extra": extra,
            "page_text": " ".join(lines),
        })
    return {"title": title, "comparisons": comparisons, "footnotes": footnotes,
            "scenarios": scenarios}


def r2(x):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def describe(title):
    """Short scenario name from the page title (drops company name lines)."""
    keep = [t for t in title if not re.search(
        r"company|gas co|energy$|corporation|utilities|grid|^\w+ gas$"
        r"|typical residential|\(r-?3\)", t, re.I)]
    return " | ".join(keep) if keep else " | ".join(title)


# ---------------------------------------------------------------------------
# Calculations (same formulas as the Excel sheet)
# ---------------------------------------------------------------------------

def _div(a, b):
    return a / b if pd.notna(a) and pd.notna(b) and b != 0 else None


def compute_peak(df):
    d = df.copy()
    for c in PEAK_INPUTS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["pct_gaf"] = [_div(p - a, a) for a, p in zip(d.prior_gaf, d.prop_gaf)]
    d["chg_bill"] = d.prop_bill - d.prior_bill
    d["pct_bill"] = [_div(c, b) for c, b in zip(d.chg_bill, d.prior_bill)]
    d["chg_gaf_only"] = (d.prop_gaf - d.prior_gaf) * d.usage
    return d


def compute_ldaf(df, usage):
    d = df.copy()
    for c in LDAF_INPUTS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["pct_ldaf"] = [_div(p - c, c) for c, p in zip(d.cur_ldaf, d.prop_ldaf)]
    d["chg_total_bill"] = usage.values * (d.prop_ldaf - d.cur_ldaf)
    return d


def build_export(d, colmap, order, avg_cols, notes=None):
    vals = d.set_index("Company")
    rows = []
    for comp, hdr, _ in COMPANIES:
        r = {"Company": comp}
        if not hdr:
            for k in order:
                v = vals.at[comp, k]
                r[colmap[k]] = None if pd.isna(v) else v
            if notes is not None:
                info = notes.get(comp, {})
                for c in NOTE_COLS:
                    r[c] = info.get(c, "")
        rows.append(r)
    if avg_cols:
        avg = {"Company": "Average"}
        for k in order:
            avg[colmap[k]] = vals[k].mean() if k in avg_cols else None
        rows.append(avg)
    cols = ["Company"] + [colmap[k] for k in order]
    if notes is not None:
        cols += NOTE_COLS
    return pd.DataFrame(rows, columns=cols)


NOTE_COLS = ["Section / scenario", "Compared from (current basis)",
             "Compared to (proposed basis)", "Source"]


ALT_INPUTS = ["cur_ldaf", "offpeak_ldaf", "alt_peak_ldaf", "alt_offpeak_ldaf",
              "usage_offpeak"]
ALT_ORDER = ["cur_ldaf", "offpeak_ldaf", "alt_peak_ldaf", "alt_offpeak_ldaf", "pct_alt",
             "chg_alt_peak", "chg_alt_off", "usage_offpeak"]


def alt_columns(prior_short, proposed_short, ldaf_date):
    return {"cur_ldaf": f" {prior_short} LDAF ({ldaf_date})",
            "offpeak_ldaf": "Revised LDAF (Off-Peak)",
            "alt_peak_ldaf": f" Alternative {proposed_short} Peak LDAF",
            "alt_offpeak_ldaf": " Alternative LDAF Off-Peak",
            "pct_alt": "% Change from Peak LDAF",
            "chg_alt_peak": " Change in Bill Peak LDAF vs. alternative",
            "chg_alt_off": " Change in Bill off-peak LDAF vs. alternative off-peak LDAF",
            "usage_offpeak": "Off-peak avg monthly usage (therms)"}


def compute_alt(df, usage):
    d = df.copy()
    for c in ALT_INPUTS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["pct_alt"] = [_div(a - c, c) for c, a in zip(d.cur_ldaf, d.alt_peak_ldaf)]
    d["chg_alt_peak"] = usage.values * (d.alt_peak_ldaf - d.cur_ldaf)
    d["chg_alt_off"] = d.usage_offpeak * (d.alt_offpeak_ldaf - d.offpeak_ldaf)
    return d


def blank_alt():
    return pd.DataFrame([{"Company": c, **{k: None for k in ALT_INPUTS}}
                         for c in DATA_COMPANIES]).astype({k: "float64" for k in ALT_INPUTS})


def build_chart(resolved, proposed):
    """One chart from the latest rates, with the source of every value."""
    chart = blank_part(f"Latest proposed rates — {proposed}")
    chart["src"], chart["built"] = {}, {}
    peak = chart["peak"].set_index("Company")
    ldaf = chart["ldaf"].set_index("Company")
    alt = chart["alt"].set_index("Company")
    calc = "Calculated: "
    for comp, res in resolved.items():
        S = res["sources"]
        bs = res.get("bill_section")
        bill_src = S.get("bills", "")
        built = {"peak": {}, "ldaf": {}, "alt": {}}
        for k, v in res["chart"].items():
            peak.at[comp, k] = v
            built["peak"][k] = v
        for k, v in res["ldaf_tbl"].items():
            ldaf.at[comp, k] = v
            built["ldaf"][k] = v
        for k, v in res["alt"].items():
            if v is not None:
                alt.at[comp, k] = v
                built["alt"][k] = v
        usage_src = (f"{bill_src} — {bs['sources'].get('usage', '')}" if bs else "")
        chart["src"][comp] = {
            "peak": {
                "prior_gaf": S.get("prior_gaf", ""),
                "prop_gaf": S.get("GAF", ""),
                "pct_gaf": calc + "(Proposed GAF − Average prior GAF) ÷ Average prior GAF",
                "usage": usage_src,
                "prior_bill": (f"{bill_src} — {bs['sources'].get('prior_bill', '')}"
                               if bs else ""),
                "prop_bill": (f"{bill_src} — {bs['sources'].get('prop_bill', '')}"
                              if bs else ""),
                "chg_bill": calc + "Proposed bill − Prior bill",
                "pct_bill": calc + "Bill change ÷ Prior bill",
                "chg_gaf_only": calc + "(Proposed GAF − Average prior GAF) × usage",
                "chg_old_ldaf": "Not in the filings — type in by hand",
            },
            "ldaf": {
                "cur_ldaf": S.get("cur_ldaf", ""),
                "reduced_ldaf": "Not in the filings — type in by hand",
                "offpeak_ldaf": S.get("offpeak_ldaf", ""),
                "prop_ldaf": S.get("LDAF", ""),
                "pct_ldaf": calc + "(Proposed LDAF − 11/1 LDAF) ÷ 11/1 LDAF",
                "prior_winter_bill": (f"{bill_src} — current bill, peak-period total"
                                      if bs else ""),
                "prop_winter_bill": (f"{bill_src} — proposed bill, peak-period total"
                                     if bs else ""),
                "chg_total_bill": calc + "usage × (Proposed LDAF − 11/1 LDAF)",
            },
            "alt": ({
                "cur_ldaf": S.get("cur_ldaf", ""),
                "offpeak_ldaf": S.get("offpeak_ldaf", ""),
                "alt_peak_ldaf": f"{S.get('alt', '')} — proposed LDAF, peak months",
                "alt_offpeak_ldaf": f"{S.get('alt', '')} — proposed LDAF, off-peak months",
                "pct_alt": calc + "(Alternative peak LDAF − 11/1 LDAF) ÷ 11/1 LDAF",
                "chg_alt_peak": calc + "peak usage × (Alternative peak LDAF − 11/1 LDAF)",
                "chg_alt_off": calc + "off-peak usage × (Alternative off-peak LDAF − "
                                      "off-peak LDAF)",
                "usage_offpeak": f"{S.get('alt', '')} — off-peak therms ÷ 6",
            } if res["alt"] else {}),
        }
        chart["built"][comp] = built
    chart["peak"], chart["ldaf"], chart["alt"] = (peak.reset_index(), ldaf.reset_index(),
                                                  alt.reset_index())
    return chart


def blank_part(name):
    peak = pd.DataFrame([{"Company": c, **{k: None for k in PEAK_INPUTS}}
                         for c in DATA_COMPANIES]).astype(
        {k: "float64" for k in PEAK_INPUTS})
    ldaf = pd.DataFrame([{"Company": c, **{k: None for k in LDAF_INPUTS}}
                         for c in DATA_COMPANIES]).astype(
        {k: "float64" for k in LDAF_INPUTS})
    return {"name": name, "peak": peak, "ldaf": ldaf, "alt": blank_alt(), "notes": {},
            "ver": 0}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def peak_chart_page():
    global PCOLS, LCOLS, FIELD_LABELS
    st.title("GAF Peak Chart Builder — R-3 Residential Heating")
    st.caption("Created by Cathy Kam")

    with st.sidebar:
        st.header("Period labels")
        prior = st.text_input("Prior peak period", "2025/26")
        proposed = st.text_input("Proposed peak period", "2026/27")
        prior_short = st.text_input("Prior (short)", "25/26")
        proposed_short = st.text_input("Proposed (short)", "26/27")
        ldaf_date = st.text_input("Current LDAF effective date", "11/1/25")
        st.divider()
        st.markdown(
            "**Pulled from each R-3 section**\n"
            "- Usage = peak-period therms ÷ 6\n"
            "- GAF = Cost of Gas Adjustment row in the Current block vs the "
            "Proposed block (usage-weighted if it varies Nov–Apr)\n"
            "- Bills = peak-period bill total ÷ 6 (plain / without-discount rows)\n"
            "- LDAF = Total LDAC row\n\n"
            "**Calculated**\n"
            "- % change GAF = (Proposed − Prior) ÷ Prior\n"
            "- Bill change = Proposed − Prior bill\n"
            "- Change due to GAF only = ΔGAF × usage\n"
            "- LDAF total-bill change = usage × ΔLDAF")

    PCOLS = peak_columns(prior, proposed, ldaf_date)
    LCOLS = ldaf_columns(prior_short, proposed_short, ldaf_date)
    ACOLS = alt_columns(prior_short, proposed_short, ldaf_date)
    FIELD_LABELS = {**PCOLS, **LCOLS}

    ss = st.session_state
    ss.setdefault("sections", [])      # every scenario found, across files

    # ---- 1. Drag and drop -----------------------------------------------------
    st.subheader("1 · Drop filings")
    files = st.file_uploader(
        "Drag and drop typical-bill schedules (PDF or Excel). Every R-3 page or "
        "sheet in each file is read; each scenario on it becomes a section.",
        type=["pdf", "xlsx", "xlsm", "xls", "csv", "txt"],
        accept_multiple_files=True)

    if files:
        assign = {}
        bar = st.progress(0.0, text="Reading files…")
        for n_f, f in enumerate(files):
            bar.progress(n_f / len(files), text=f"Reading {f.name} ({n_f + 1} of {len(files)})…")
            try:
                pages = read_pages(f.name, f.getvalue())
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not read {f.name}: {e}")
                continue
            comp = guess_company(f.name, pages)
            r3 = [p for p in pages if is_r3_page(p[1])]
            c1, c2 = st.columns([3, 2])
            c1.write(f"**{f.name}** — {len(pages)} page(s), "
                     f"{len(r3)} R-3 page(s): {', '.join(p[0] for p in r3) or 'none'}")
            if not r3:
                c1.caption("No R-3 heading found; every page will be tried.")
            assign[f.name] = (c2.selectbox(
                "Company", ["— skip —"] + DATA_COMPANIES,
                index=DATA_COMPANIES.index(comp) + 1 if comp else 0,
                key=f"co_{f.name}", label_visibility="collapsed"), r3 or pages, pages)
        bar.empty()

        if st.button("Identify sections", type="primary"):
            sections = []
            import latest_rates as lr
            metas = {}
            for fname, (comp, pages, all_pages) in assign.items():
                if comp == "— skip —":
                    continue
                metas[fname] = lr.file_meta(fname, all_pages)
                n_in_file = 0
                for plabel, lines in pages:
                    parsed = parse_page(lines)
                    for k, sc in enumerate(parsed["scenarios"], 1):
                        if not sc["values"]:
                            continue
                        n_in_file += 1
                        name = describe(parsed["title"]) or plabel
                        if len(parsed["scenarios"]) > 1:
                            name += f" — scenario {k}: {sc['proposed_basis']}"
                        sections.append({
                            "id": f"{fname}|{plabel}|{k}", "company": comp,
                            "file": fname, "page": plabel, "name": name,
                            "title": parsed["title"],
                            "comparisons": parsed["comparisons"],
                            "footnotes": parsed["footnotes"], **sc,
                            "part": 0,                   # manual assignment only
                        })
            ss.sections = sections
            ss.file_meta = lr.resolve_dates(metas)
            st.rerun()

    # ---- 2. Latest rates and scenario comparison -------------------------
    if ss.sections:
        import latest_rates as lr
        metas = ss.get("file_meta", {})
        st.subheader("2 · Latest GAF / LDAF and scenario comparison")
        if metas:
            st.dataframe(pd.DataFrame([{
                "File": n, "Filing type": m["subject"] or "—",
                "Revised": "Yes" if m["revised"] else "",
                "Filed": (m["filed"].strftime("%m/%d/%Y") + (" (from another filing's "
                          "reference)" if m.get("filed_inferred") else "")) if m["filed"] else "—",
                "Summary table (R-3)": ", ".join(f"{k} {v[0]:.4f}" for k, v in
                                                 m["summary"].items())}
                for n, m in metas.items()]), hide_index=True, width="stretch")
        st.caption("Latest rate = GAF from the cost-of-gas (CGAC) filing, LDAF from the "
                   "LDAC filing, among scenarios that actually propose the rate; then the "
                   "most recently filed and Revised documents; summary tables (Form IIA) "
                   "over typical-bill pages. Illustrative / re-allocation scenarios go to "
                   "the Alternative LDAF table, not the chart.")
        by_co = {}
        for s in ss.sections:
            by_co.setdefault(s["company"], []).append(s)
        resolved = {}
        for comp, secs in by_co.items():
            res = lr.resolve_company(secs, metas)
            resolved[comp] = res
            with st.container(border=True):
                st.markdown(f"#### {comp}")
                lt, ch, lt2 = res["latest"], res["chart"], res["ldaf_tbl"]
                summ = [
                    ("Latest proposed GAF", ch.get("prop_gaf"), res["sources"].get("GAF")),
                    ("Latest proposed LDAF", lt2.get("prop_ldaf"), res["sources"].get("LDAF")),
                    ("Average prior peak GAF", ch.get("prior_gaf"),
                     res["sources"].get("prior_gaf")),
                    ("Current peak LDAF (11/1)", lt2.get("cur_ldaf"),
                     res["sources"].get("cur_ldaf")),
                    ("Off-peak LDAF", lt2.get("offpeak_ldaf"), res["sources"].get("offpeak_ldaf")),
                    ("Monthly bill (prior → proposed)",
                     (f"${ch['prior_bill']:,.2f} → ${ch['prop_bill']:,.2f}"
                      if ch.get("prior_bill") is not None and ch.get("prop_bill") is not None
                      else None), res["sources"].get("bills")),
                ]
                if res["alt"]:
                    a = res["alt"]
                    summ.append(("Alternative LDAF (peak / off-peak)",
                                 f"{a.get('alt_peak_ldaf') or 0:.4f} / "
                                 f"{a.get('alt_offpeak_ldaf') or 0:.4f}",
                                 res["sources"].get("alt")))
                st.dataframe(pd.DataFrame([{
                    "Item": k, "Value": (f"{v:.4f}" if isinstance(v, float) else (v or "—")),
                    "Taken from": src or "not found in the filings"} for k, v, src in summ]),
                    hide_index=True, width="stretch")
                for n in res["notes"]:
                    st.warning(n)
                st.markdown("**Every scenario the company filed**")
                cmp_df = pd.DataFrame(res["compare"])
                st.dataframe(cmp_df, hide_index=True, width="stretch",
                             column_config={"Compared from": st.column_config.TextColumn(width="medium"),
                                            "Compared to": st.column_config.TextColumn(width="medium")})
        ss.resolved = resolved

    # ---- scenario details (reference only) ---------------------------------
    if ss.sections:
        with st.expander(f"Details of all {len(ss.sections)} scenario sections the "
                         "company filed (reference)", expanded=False):
            for s in ss.sections:
                with st.container(border=True):
                    st.markdown(f"**{s['company']}** · {s['name']}  \n"
                                f"`{s['file']}` {s['page']}")
                    st.markdown(
                        f"- **Compared from (current basis):** {s['current_basis']}\n"
                        f"- **Compared to:** {s.get('compared_line') or s['proposed_basis']}\n"
                        + (f"- **Footnotes:** {' '.join(s['footnotes'])}\n"
                           if s["footnotes"] else ""))
                    st.dataframe(pd.DataFrame([
                        {"Field": FIELD_LABELS.get(k, k), "Value": v,
                         "Source on the page": s["sources"].get(k, "")}
                        for k, v in s["values"].items()]), hide_index=True, width="stretch")
                    for n in s["notes"]:
                        st.info(n)

    # ---- 3. The chart ------------------------------------------------------
    resolved = ss.get("resolved", {})
    sig = tuple(s["id"] for s in ss.sections)
    if "chart" not in ss or ss.get("chart_sig") != sig:
        ss.chart = build_chart(resolved, proposed)
        ss.chart_sig = sig
    chart = ss.chart

    st.subheader(f"3 · Peak chart — latest proposed rates ({proposed}, R-3)")
    if not resolved:
        st.caption("Drop filings and click **Identify sections** — the chart fills "
                   "itself from the latest rates. You can also type values directly.")
    else:
        st.caption("Filled from the latest rates in step 2. Edit any white cell; "
                   "under each table, *Where each number comes from* names the file, "
                   "section, page and basis behind every value.")
        if st.button("Reset chart to the latest rates"):
            ss.chart = build_chart(resolved, proposed)
            st.rerun()

    pfmt = {PCOLS[k]: "{:.4f}" for k in ["prior_gaf", "prop_gaf"]}
    pfmt.update({PCOLS[k]: "{:.2%}" for k in ["pct_gaf", "pct_bill"]})
    pfmt.update({PCOLS[k]: "${:,.2f}" for k in ["prior_bill", "prop_bill", "chg_bill",
                                                 "chg_gaf_only", "chg_old_ldaf"]})
    pfmt[PCOLS["usage"]] = "{:.2f}"
    lfmt = {LCOLS[k]: "{:.4f}" for k in ["cur_ldaf", "reduced_ldaf",
                                         "offpeak_ldaf", "prop_ldaf"]}
    lfmt[LCOLS["pct_ldaf"]] = "{:.2%}"
    lfmt.update({LCOLS[k]: "${:,.2f}" for k in ["prior_winter_bill",
                                                 "prop_winter_bill", "chg_total_bill"]})
    afmt = {ACOLS[k]: "{:.4f}" for k in ["cur_ldaf", "offpeak_ldaf",
                                         "alt_peak_ldaf", "alt_offpeak_ldaf"]}
    afmt[ACOLS["pct_alt"]] = "{:.2%}"
    afmt.update({ACOLS[k]: "${:,.2f}" for k in ["chg_alt_peak", "chg_alt_off"]})
    afmt[ACOLS["usage_offpeak"]] = "{:.2f}"

    def source_table(table_key, colmap, order, current, inputs):
        rows = []
        cur = current.set_index("Company")
        for comp in DATA_COMPANIES:
            src = chart["src"].get(comp, {}).get(table_key, {})
            if not src and cur.loc[comp].isna().all():
                continue
            for k in order:
                v = cur.at[comp, k] if k in cur.columns else None
                built = chart["built"].get(comp, {}).get(table_key, {}).get(k)
                origin = src.get(k, "")
                if k in inputs and pd.notna(v) and (built is None or abs(v - built) > 1e-9):
                    origin = "Typed in by hand"
                if not origin and (k not in cur.columns or pd.isna(v)):
                    continue
                rows.append({"Company": comp, "Column": colmap[k].strip(),
                             "Value": ("" if v is None or pd.isna(v) else
                                       f"{v:.2%}" if k.startswith("pct") else
                                       f"{v:.4f}" if ("gaf" in k or "ldaf" in k) and not k.startswith("chg")
                                       else f"{v:,.2f}"),
                             "Where it comes from": origin or "Calculated"})
        return pd.DataFrame(rows)

    sources_out = []

    # peak chart
    st.markdown("**Peak chart**")
    cfg = {"Company": st.column_config.TextColumn(disabled=True)}
    for k in PEAK_INPUTS:
        f = "%.4f" if "gaf" in k else ("%.2f" if k == "usage" else "$%.2f")
        cfg[k] = st.column_config.NumberColumn(PCOLS[k], format=f)
    peak_in = st.data_editor(chart["peak"], column_config=cfg, hide_index=True,
                             width="stretch", key=f"peak_ed_{chart['ver']}")
    peak_calc = compute_peak(peak_in)
    peak_out = build_export(peak_calc, PCOLS, PEAK_ORDER,
                            avg_cols=[k for k in PEAK_ORDER if k != "usage"])
    st.dataframe(peak_out.style.format(pfmt, na_rep=""), hide_index=True, width="stretch")
    src_peak = source_table("peak", PCOLS, PEAK_ORDER, peak_calc, PEAK_INPUTS)
    if not src_peak.empty:
        with st.expander("Where each number in the peak chart comes from"):
            st.dataframe(src_peak, hide_index=True, width="stretch")
        sources_out.append(("Peak chart", src_peak))

    # LDAF table
    st.markdown("**Residential-Heating LDAF**")
    lcfg = {"Company": st.column_config.TextColumn(disabled=True)}
    for k in LDAF_INPUTS:
        lcfg[k] = st.column_config.NumberColumn(
            LCOLS[k], format="$%.2f" if "bill" in k else "%.4f")
    ldaf_in = st.data_editor(chart["ldaf"], column_config=lcfg, hide_index=True,
                             width="stretch", key=f"ldaf_ed_{chart['ver']}")
    ldaf_calc = compute_ldaf(ldaf_in, peak_calc["usage"])
    ldaf_out = build_export(ldaf_calc, LCOLS, LDAF_ORDER, avg_cols=[])
    st.dataframe(ldaf_out.style.format(lfmt, na_rep=""), hide_index=True, width="stretch")
    src_ldaf = source_table("ldaf", LCOLS, LDAF_ORDER, ldaf_calc, LDAF_INPUTS)
    if not src_ldaf.empty:
        with st.expander("Where each number in the LDAF table comes from"):
            st.dataframe(src_ldaf, hide_index=True, width="stretch")
        sources_out.append(("Residential-Heating LDAF", src_ldaf))

    # alternative LDAF table
    st.markdown("**Alternative Residential LDAF to split costs with off-peak**")
    acfg = {"Company": st.column_config.TextColumn(disabled=True)}
    for k in ALT_INPUTS:
        acfg[k] = st.column_config.NumberColumn(
            ACOLS[k], format="%.2f" if k == "usage_offpeak" else "%.4f")
    alt_in = st.data_editor(chart["alt"], column_config=acfg, hide_index=True,
                            width="stretch", key=f"alt_ed_{chart['ver']}")
    alt_calc = compute_alt(alt_in, peak_calc["usage"])
    alt_out = build_export(alt_calc, ACOLS, ALT_ORDER, avg_cols=[])
    st.dataframe(alt_out.style.format(afmt, na_rep=""), hide_index=True, width="stretch")
    src_alt = source_table("alt", ACOLS, ALT_ORDER, alt_calc, ALT_INPUTS)
    if not src_alt.empty:
        with st.expander("Where each number in the alternative LDAF table comes from"):
            st.dataframe(src_alt, hide_index=True, width="stretch")
        sources_out.append(("Alternative Residential LDAF", src_alt))

    # ---- 4. Export ---------------------------------------------------------
    st.subheader("4 · Export")
    stamp = proposed_short.replace("/", "-")
    out_csv = (f"{proposed_short} PEAK chart (R-3) — latest proposed rates\n"
               + peak_out.to_csv(index=False)
               + "\n,Residential-Heating LDAF\n" + ldaf_out.to_csv(index=False)
               + "\n,Alternative Residential LDAF to split costs with off-peak\n"
               + alt_out.to_csv(index=False))
    for title_, df_ in sources_out:
        out_csv += f"\n,Where each number comes from — {title_}\n" + df_.to_csv(index=False)
    st.download_button("Download CSV", out_csv.encode("utf-8-sig"),
                       file_name=f"{stamp}_PEAK_chart.csv", mime="text/csv", type="primary")
    st.caption("One file: the three tables, then the source of every value.")

    # keep edits across reruns
    chart["peak"], chart["ldaf"], chart["alt"] = peak_in, ldaf_in, alt_in

    if st.button("Clear everything"):
        for k in [k for k in ss.keys() if not str(k).startswith("mg_")]:
            del ss[k]
        st.rerun()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
from massgov_page import massgov_page  # noqa: E402

st.set_page_config(page_title="GAF Peak Chart Builder", layout="wide")
st.navigation([
    st.Page(peak_chart_page, title="Peak chart (R-3)", icon="📊", default=True),
    st.Page(massgov_page, title="Mass.gov rate page", icon="🌐",
            url_path="massgov"),
]).run()
