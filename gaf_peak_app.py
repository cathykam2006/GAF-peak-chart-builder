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

def read_pages(name, data):
    lname = name.lower()
    pages = []
    if lname.endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                pages.append((f"p.{i}", (page.extract_text() or "").splitlines()))
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
    return (m.group(1) == "3") if m else "residential heating" in cls


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
        vals, src, notes = {}, {}, []
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
            "values": vals, "sources": src, "notes": notes,
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


def blank_part(name):
    peak = pd.DataFrame([{"Company": c, **{k: None for k in PEAK_INPUTS}}
                         for c in DATA_COMPANIES]).astype(
        {k: "float64" for k in PEAK_INPUTS})
    ldaf = pd.DataFrame([{"Company": c, **{k: None for k in LDAF_INPUTS}}
                         for c in DATA_COMPANIES]).astype(
        {k: "float64" for k in LDAF_INPUTS})
    return {"name": name, "peak": peak, "ldaf": ldaf, "notes": {}, "ver": 0}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="GAF Peak Chart Builder", layout="wide")
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
FIELD_LABELS = {**PCOLS, **LCOLS}

ss = st.session_state
ss.setdefault("parts", [blank_part("Part 1")])
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
    for f in files:
        pages = read_pages(f.name, f.getvalue())
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
            key=f"co_{f.name}", label_visibility="collapsed"), r3 or pages)

    if st.button("Identify sections", type="primary"):
        sections = []
        for fname, (comp, pages) in assign.items():
            if comp == "— skip —":
                continue
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
                        "part": n_in_file,           # default: n-th scenario -> Part n
                    })
        ss.sections = sections
        need = max([s["part"] for s in sections], default=1)
        while len(ss.parts) < need:
            ss.parts.append(blank_part(f"Part {len(ss.parts) + 1}"))
        st.rerun()

# ---- 2. Sections found -------------------------------------------------
if ss.sections:
    st.subheader("2 · Sections identified — what each one compares")
    st.caption("Check the basis of each section, then choose which Part "
               "(chart) it goes into. Sections that compare different things "
               "should go into different Parts.")
    part_opts = ["skip"] + [f"Part {i + 1}" for i in range(len(ss.parts))] \
        + ["+ new Part"]
    by_co = {}
    for s in ss.sections:
        by_co.setdefault(s["company"], []).append(s)
    for comp, secs in by_co.items():
        if len(secs) > 1:
            st.warning(f"{comp}: {len(secs)} sections found — they compare "
                       "different scenarios; confirm which Part each belongs in.")
        for s in secs:
            with st.container(border=True):
                top = st.columns([4, 1])
                top[0].markdown(f"**{comp}** · {s['name']}  \n"
                                f"`{s['file']}` {s['page']}")
                default = f"Part {s['part']}" if s["part"] <= len(ss.parts) else "skip"
                s["part_choice"] = top[1].selectbox(
                    "Part", part_opts, index=part_opts.index(default),
                    key=f"part_{s['id']}")
                if s["compared_line"]:
                    st.markdown(f"#### 🔎 {s['compared_line']}")
                st.markdown(
                    f"- **Compared from (current basis):** {s['current_basis']}\n"
                    f"- **Compared to (proposed basis):** {s['proposed_basis']}\n"
                    f"- **Page title:** {' / '.join(s['title']) or '—'}\n"
                    + (f"- **Comparisons on page:** {'; '.join(s['comparisons'])}\n"
                       if s["comparisons"] else "")
                    + (f"- **Footnotes:** {' '.join(s['footnotes'])}\n"
                       if s["footnotes"] else ""))
                vt = pd.DataFrame([
                    {"Field": FIELD_LABELS.get(k, k), "Value": v,
                     "Source": s["sources"].get(k, "")}
                    for k, v in s["values"].items()])
                st.dataframe(vt, hide_index=True, width="stretch")
                for n in s["notes"]:
                    st.info(n)

    if st.button("Fill Parts from sections", type="primary"):
        for s in ss.sections:
            ch = s.get("part_choice", "skip")
            if ch == "skip":
                continue
            if ch == "+ new Part":
                ss.parts.append(blank_part(f"Part {len(ss.parts) + 1}"))
                idx = len(ss.parts) - 1
            else:
                idx = int(ch.split()[1]) - 1
            part = ss.parts[idx]
            peak = part["peak"].set_index("Company")
            ldaf = part["ldaf"].set_index("Company")
            for k, v in s["values"].items():
                if v is None:
                    continue
                (peak if k in PEAK_INPUTS else ldaf).at[s["company"], k] = v
            part["peak"], part["ldaf"] = peak.reset_index(), ldaf.reset_index()
            part["notes"][s["company"]] = {
                NOTE_COLS[0]: s["name"],
                NOTE_COLS[1]: s["current_basis"],
                NOTE_COLS[2]: (s["proposed_basis"]
                               + (f" — {s['compared_line']}" if s["compared_line"] else "")),
                NOTE_COLS[3]: f"{s['file']} {s['page']}",
            }
            if part["name"] == f"Part {idx + 1}":
                part["name"] = f"Part {idx + 1} — {s['name']}"
            part["ver"] += 1
        st.rerun()

# ---- 3. Parts ----------------------------------------------------------
st.subheader("3 · Parts (one chart each)")
if st.button("+ Add empty Part"):
    ss.parts.append(blank_part(f"Part {len(ss.parts) + 1}"))
    st.rerun()

exports = []
tabs = st.tabs([p["name"][:40] for p in ss.parts])
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

for i, (tab, part) in enumerate(zip(tabs, ss.parts)):
    with tab:
        part["name"] = st.text_input("Part name (goes in the CSV)", part["name"],
                                     key=f"pname_{i}")
        st.markdown("**Peak chart** — edit inputs here")
        cfg = {"Company": st.column_config.TextColumn(disabled=True)}
        for k in PEAK_INPUTS:
            f = "%.4f" if "gaf" in k else ("%.2f" if k == "usage" else "$%.2f")
            cfg[k] = st.column_config.NumberColumn(PCOLS[k], format=f)
        peak_in = st.data_editor(part["peak"], column_config=cfg, hide_index=True,
                                 width="stretch",
                                 key=f"peak_{i}_{part['ver']}")
        peak_calc = compute_peak(peak_in)
        peak_out = build_export(peak_calc, PCOLS, PEAK_ORDER,
                                avg_cols=[k for k in PEAK_ORDER if k != "usage"],
                                notes=part["notes"])
        st.dataframe(peak_out.style.format(pfmt, na_rep=""), hide_index=True,
                     width="stretch")

        st.markdown("**Residential-Heating LDAF**")
        lcfg = {"Company": st.column_config.TextColumn(disabled=True)}
        for k in LDAF_INPUTS:
            lcfg[k] = st.column_config.NumberColumn(
                LCOLS[k], format="$%.2f" if "bill" in k else "%.4f")
        ldaf_in = st.data_editor(part["ldaf"], column_config=lcfg, hide_index=True,
                                 width="stretch",
                                 key=f"ldaf_{i}_{part['ver']}")
        ldaf_out = build_export(compute_ldaf(ldaf_in, peak_calc["usage"]),
                                LCOLS, LDAF_ORDER, avg_cols=[])
        st.dataframe(ldaf_out.style.format(lfmt, na_rep=""), hide_index=True,
                     width="stretch")

        stamp = proposed_short.replace("/", "-")
        safe = re.sub(r"[^A-Za-z0-9]+", "_", part["name"])[:40].strip("_")
        part_csv = (f"{part['name']}\n" + peak_out.to_csv(index=False)
                    + "\n,Residential-Heating LDAF\n" + ldaf_out.to_csv(index=False))
        st.download_button(f"Download {part['name'][:30]} CSV",
                           part_csv.encode("utf-8-sig"),
                           file_name=f"{stamp}_PEAK_{safe}.csv", mime="text/csv",
                           key=f"dl_{i}")
        exports.append(part_csv)

        # keep edits without resetting the editor on every rerun
        part["peak_live"], part["ldaf_live"] = peak_in, ldaf_in

# ---- 4. Export all -----------------------------------------------------
st.subheader("4 · Export")
st.download_button("Download all Parts in one CSV",
                   "\n\n".join(exports).encode("utf-8-sig"),
                   file_name=f"{proposed_short.replace('/', '-')}_PEAK_all_parts.csv",
                   mime="text/csv", type="primary")

# Commit live edits into the base tables before the next fill so manual edits
# survive "Fill Parts from sections".
for part in ss.parts:
    if "peak_live" in part:
        part["peak"] = part.pop("peak_live")
        part["ldaf"] = part.pop("ldaf_live")

if st.button("Clear everything"):
    for k in list(ss.keys()):
        del ss[k]
    st.rerun()
