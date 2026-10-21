"""
Mass.gov rate page builder
--------------------------
Second page of the GAF Peak Chart Builder.  Created by Cathy Kam.

Drag and drop PDFs, pull the GAF / LDAF rates out of them, and export the
result in the format of "Information on Gas Supply and Delivery Charges"
(https://www.mass.gov/info-details/information-on-gas-supply-and-delivery-charges).

PDFs that are recognised:
  * company filings with typical-bill schedules (e.g. Attachment
    DPU-LDC-2-3(d)(3)): proposed CGA (GAF) and Total LDAC (LDAF) by rate class
  * rate tables listing GAF and/or LDAF by rate class (R-1, G-41, T-54, ...)
  * a PDF of the mass.gov page itself (File > Print > Save as PDF): read as the
    posted section that the new one is built from
"""

import copy
import html as htmlmod
import io
import re
from datetime import date, datetime, timedelta
import calendar

import pandas as pd
import streamlit as st

PAGE_URL = ("https://www.mass.gov/info-details/"
            "information-on-gas-supply-and-delivery-charges")
HEADER = ["Rate Class", "Billing Unit", "GAF", "LDAF"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]

SECTION_RE = re.compile(
    r"(?P<season>Peak/Winter|Off-Peak/Summer)\s+(?P<yr>\d{4}(?:\s*-\s*\d{4})?)\s+"
    r"Rates(?:\s+Revision\s+(?P<rev>\d+))?\s*\(\s*Effective\s+(?P<start>[\d/]+)"
    r"\s+(?:through|to|-)\s+(?P<end>[\d/]+)\s*\)", re.I)
HEADER_RE = re.compile(r"^\s*Rate Class\s+Billing Unit\s+GAF\s+LDAF\s*$", re.I)
ROW_RE = re.compile(r"^(?P<cls>.+?)\s+(?P<unit>\$/\s?[A-Za-z]+(?:\s+Therms)?)"
                    r"(?:\s+(?P<gaf>-?\d*\.\d+|-?\d+))?(?:\s+(?P<ldaf>-?\d*\.\d+|-?\d+))?\s*$")
REVISED_RE = re.compile(r"\s*REVISED\s*$")
COMPANY_KEYS = ["berkshire", "eversource gas company", "bay state", "fitchburg",
                "unitil", "blackstone", "north attleboro", "fall river",
                "boston gas", "colonial", "nstar"]

# Last posted section, used as the starting layout until a PDF of the page is
# dropped (companies, notes, rate classes and current values).
DEFAULT_PAGE_TEXT = """Off-Peak/Summer 2026 Rates Revision 3 (Effective 10/1/26 through 10/31/26)
Berkshire Gas Company
On July 31, 2026, the Department approved a settlement agreement between the company and the Attorney General in Berkshire Gas Company, D.P.U. 25-170. As a result, the GAF for all rate classes were revised on April 1, 2026.
All Residential\t$/Therm\t0.3194\t0.9631
G-41/G-51\t$/Therm\t0.3194\t0.2702
G-42/G-52\t$/Therm\t0.3194\t0.2238
G-43/G-53\t$/Therm\t0.3194\t0.1689
T-54\t$/Therm\t0.3194\t0.0126
Eversource Gas Company of Massachusetts (formerly Bay State Gas d/b/a Columbia Gas of Massachusetts)REVISED
Beginning with the 2025–2026 heating season, Eversource has introduced a redesigned gas bill for its customers. You can view the company’s sample bill for details.
Residential Non-Heating R-1, R-2\t$/Therm\t0.2540\t0.6564
Residential Heating R-3, R-4\t$/Therm\t0.3145\t0.6564
G-40\t$/Therm\t0.3145\t0.4124
G-41\t$/Therm\t0.3145\t0.3052
G-42\t$/Therm\t0.3145\t0.3425
G-43\t$/Therm\t0.3145\t0.2957
G-50\t$/Therm\t0.2540\t0.4124
G-51\t$/Therm\t0.2540\t0.3052
G-52\t$/Therm\t0.2540\t0.3425
G-53\t$/Therm\t0.2540\t0.2957
Fitchburg Gas d/b/a Unitil
Residential Non-Heating R-1, R-2\t$/Therm\t0.3014\t1.3370
Residential Heating R-3, R-4\t$/Therm\t0.3468\t1.7437
G-41\t$/Therm\t0.3468\t0.6269
G-42\t$/Therm\t0.3468\t0.4667
G-43\t$/Therm\t0.3468\t0.4309
G-51\t$/Therm\t0.3014\t0.6269
G-52\t$/Therm\t0.3014\t0.4667
G-53\t$/Therm\t0.3014\t0.4309
Liberty Utilities - Blackstone (formerly Blackstone Gas Company)
All Residential\t$/Therm\t0.1697\t0.3617
G-41, G-42, G-43\t$/Therm\t0.1697\t0.3402
G-51, G-52, G-53\t$/Therm\t0.1697\t0.3417
Liberty Utilities - North Attleboro/Fall River
All Residential\t$/Therm\t0.4047\t0.5114
G-41, G-42, G-43\t$/Therm\t0.4047\t0.4626
G-51, G-52, G-53\t$/Therm\t0.4047\t0.3913
National Grid - Boston GasREVISED
All Residential\t$/Therm\t0.3084\t1.0016
G-41B/E, G-51B/E\t$/Therm\t0.3084\t0.4637
G-42B/E, G-52B/E\t$/Therm\t0.3084\t0.4170
G-43B/E, G-53B/E\t$/Therm\t0.3084\t0.4046
G-44B, G-54B\t$/Therm\t0.2180\t0.3496
G-44B, G-54B\t$/MDCQ Therms\t0.6907\t
National Grid - former Colonial GasREVISED
All Residential\t$/Therm\t0.3084\t0.8279
G-41, G-51\t$/Therm\t0.3084\t0.2867
G-42, G-52\t$/Therm\t0.3084\t0.2814
G-43, G-53\t$/Therm\t0.3084\t0.2357
NSTAR Gas Company d/b/a Eversource Energy
Beginning with the 2025–2026 heating season, Eversource has introduced a redesigned gas bill for its customers. You can view the company’s sample bill for details.
All Residential\t$/Therm\t0.3842\t0.7200
G-41, G-51\t$/Therm\t0.3842\t0.3871
G-42, G-52\t$/Therm\t0.3842\t0.3312
Large C&I G-43, G-53\t$/Therm\t0.3842\t0.2579
"""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def to_num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return None if pd.isna(s) else float(s)
    t = str(s).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[()\$,\s]", "", t)
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def fmt_rate(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    v = float(v)
    return f"{v:.4f}" if abs(round(v, 4) - v) < 1e-12 else f"{v:.6f}".rstrip("0")


def parse_date(s):
    for f in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.strip(), f).date()
        except ValueError:
            pass
    return None


def mdy(d):
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


def company_key(text):
    low = text.lower()
    # NSTAR filings also say "Eversource", so test it first
    for k in ["nstar"] + [k for k in COMPANY_KEYS if k != "nstar"]:
        if k in low:
            return {"bay state": "eversource gas company", "unitil": "fitchburg",
                    "fall river": "north attleboro"}.get(k, k)
    return None


def new_section(title):
    m = SECTION_RE.search(title)
    sec = {"title": title.strip(), "companies": [], "season": None, "yr": None,
           "rev": 0, "start": None, "end": None}
    if m:
        sec.update(season=m["season"], yr=re.sub(r"\s", "", m["yr"]),
                   rev=int(m["rev"] or 0), start=parse_date(m["start"]),
                   end=parse_date(m["end"]))
    return sec


def new_company(heading):
    return {"name": REVISED_RE.sub("", heading).strip(),
            "revised": bool(REVISED_RE.search(heading)), "notes": [], "rows": []}


def make_row(cells):
    cells = [c.strip() for c in cells] + [""] * 4
    return {"Rate Class": cells[0], "Billing Unit": cells[1],
            "GAF": to_num(cells[2]), "LDAF": to_num(cells[3])}


# ---------------------------------------------------------------------------
# Mass.gov page text (from a PDF of the page, or the built-in default)
# ---------------------------------------------------------------------------

def parse_page_text(text):
    sections, sec, comp = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or HEADER_RE.match(line.replace("\t", " ")):
            continue
        if SECTION_RE.search(line):
            sec, comp = new_section(SECTION_RE.search(line).group(0)), None
            sections.append(sec)
            continue
        if sec is None:
            continue
        cells = raw.split("\t")
        row = None
        if len(cells) >= 3 and cells[1].strip().startswith("$"):
            row = make_row(cells)
        else:
            m = ROW_RE.match(line)
            if m:
                row = make_row([m["cls"], m["unit"], m["gaf"] or "", m["ldaf"] or ""])
        if row:
            if comp is None:
                comp = new_company("(company not named)")
                sec["companies"].append(comp)
            comp["rows"].append(row)
            continue
        is_name = company_key(line) and len(line) < 170 and (comp is None or comp["rows"])
        if is_name:
            comp = new_company(line)
            sec["companies"].append(comp)
        elif comp is not None and not comp["rows"]:
            # a company name wrapped onto a second line in the PDF
            if not comp["notes"] and comp["name"].count("(") > comp["name"].count(")"):
                joined = comp["name"] + " " + line
                comp["name"] = REVISED_RE.sub("", joined).strip()
                comp["revised"] = comp["revised"] or bool(REVISED_RE.search(joined))
            # a note wrapped across lines: join until it ends with a full stop
            elif comp["notes"] and not comp["notes"][-1].rstrip().endswith((".", ":")):
                comp["notes"][-1] += " " + line
            else:
                comp["notes"].append(line)
    return [s for s in sections if s["companies"]]


# ---------------------------------------------------------------------------
# Rate extraction from filings
# ---------------------------------------------------------------------------
NUM_TOKEN = re.compile(r"^(\(\$?-?[\d,]*\.?\d+%?\)|-?\$?-?[\d,]*\.?\d+%?)$")
CLASS_CODE_RE = re.compile(r"\b([RGT])\s?-\s?(\d{1,2})[A-Z]?\b")
RATE_RE = re.compile(r"\(?-?\$?\d*\.\d{3,6}\)?")
GAF_LABEL = re.compile(r"cost of gas|\bcga\b|\bgaf\b|gas adjustment factor", re.I)
LDAF_LABEL = re.compile(r"total ldac|\bldac\b|\bldaf\b|local distribution adjustment", re.I)
PROPOSED = re.compile(r"^(proposed|illustrative|new|revised)\b|proposed/illustrative"
                      r"|proposed rates|illustrative rates", re.I)
CURRENT = re.compile(r"^(current|present|existing|approved)\b|rates in effect", re.I)


def split_row(line):
    toks = line.split()
    vals = []
    while toks and NUM_TOKEN.match(toks[-1]):
        vals.append(to_num(toks.pop()))
    vals.reverse()
    label = re.sub(r"^\d+\s*(?=[A-Za-z(])", "", " ".join(toks)).strip()
    return label, vals


def class_codes(text):
    """'G-41B/E, G-51B/E' -> {'G-41','G-51'}; adds RES / RES-H / RES-NH tags."""
    t = text.upper()
    codes = {f"{a}-{b}" for a, b in CLASS_CODE_RE.findall(t)}
    # "G-41/G-51" and "G-41, G-42, G-43" are covered; also "G-41/51"
    for a, b, rest in re.findall(r"\b([RGT])-(\d{1,2})[A-Z]?((?:\s*/\s*\d{1,2}[A-Z]?)+)", t):
        for n in re.findall(r"\d{1,2}", rest):
            codes.add(f"{a}-{n}")
    low = text.lower()
    if "residential" in low:
        if "non-heating" in low or "non heating" in low:
            codes.add("RES-NH")
        elif "heating" in low:
            codes.add("RES-H")
        else:
            codes.add("RES")
    return codes


def month_order(lines):
    for line in lines[:30]:
        found = re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                           line.lower())
        if len(found) >= 10:
            return found[:12]
    return None


def extract_schedule(lines, month):
    """Typical-bill schedule page: one rate class per page, monthly columns.
    Returns dict or None."""
    head = " ".join(lines[:15])
    cls_line = next((l for l in lines[:15] if re.search(r"typical|residential|rate\s+[RG]-?\d",
                                                        l, re.I) and CLASS_CODE_RE.search(l.upper())), None)
    order = month_order(lines)
    if not cls_line or not order:
        return None
    codes = {f"{a}-{b}" for a, b in CLASS_CODE_RE.findall(cls_line.upper())}
    block, found = "current", {"current": {}, "proposed": {}}
    in_body = False            # block headers only count below the month header
    for line in lines:
        if not in_body:
            in_body = len(re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov"
                                     r"|dec)", line.lower())) >= 10
            continue
        label, vals = split_row(line)
        if len(vals) < 3:
            txt = re.sub(r"^\d+\s*", "", line).strip()
            if PROPOSED.search(txt):
                block = "proposed"
            elif CURRENT.search(txt):
                block = "current"
            continue
        if len(vals) < 12 or re.search(r"recon|exogenous", label, re.I):
            continue
        kind = ("LDAF" if LDAF_LABEL.search(label)
                else "GAF" if GAF_LABEL.search(label) else None)
        if not kind or kind in found[block]:
            continue
        idx = order.index(month) if month in order else 0
        found[block][kind] = (vals[idx], label)
    if not found["proposed"] and not found["current"]:
        return None
    use = found["proposed"] or found["current"]
    return {"class_line": re.sub(r"^\d+\s*", "", cls_line).strip(), "codes": codes,
            "gaf": use.get("GAF", (None, ""))[0], "ldaf": use.get("LDAF", (None, ""))[0],
            "which": "proposed" if found["proposed"] else "current",
            "cur_gaf": found["current"].get("GAF", (None, ""))[0],
            "cur_ldaf": found["current"].get("LDAF", (None, ""))[0],
            "low_income": bool(re.search(r"low income", head, re.I))}


def extract_table_rows(lines):
    """Generic rate table: lines naming a rate class followed by $/therm rates."""
    out = []
    col_kinds = None          # e.g. ["GAF","LDAF"] from the nearest header
    page_kind = None
    head = " ".join(lines[:12])
    if LDAF_LABEL.search(head) and not GAF_LABEL.search(head):
        page_kind = "LDAF"
    elif GAF_LABEL.search(head) and not LDAF_LABEL.search(head):
        page_kind = "GAF"
    for line in lines:
        low = line.lower()
        g, l_ = GAF_LABEL.search(line), LDAF_LABEL.search(line)
        codes = class_codes(line)
        rates = [to_num(x) for x in RATE_RE.findall(line)]
        rates = [r for r in rates if r is not None and -1 < r < 5]
        if (g or l_) and not rates:
            kinds = sorted([(m.start(), k) for m, k in ((g, "GAF"), (l_, "LDAF")) if m])
            col_kinds = [k for _, k in kinds]
            continue
        if not codes or not rates:
            continue
        label = re.split(r"\s\(?-?\$?\d*\.\d{3,6}", line)[0].strip()
        gaf = ldaf = None
        if col_kinds and len(col_kinds) == 2 and len(rates) >= 2:
            vals = dict(zip(col_kinds, rates[:2]))
            gaf, ldaf = vals.get("GAF"), vals.get("LDAF")
        elif col_kinds and len(col_kinds) == 2 and len(rates) == 1:
            gaf = rates[0] if "mdcq" in low or "demand" in low else None
            ldaf = None if gaf is not None else rates[0]
            if gaf is None and ldaf is None:
                continue
        elif col_kinds and len(col_kinds) == 1:
            gaf, ldaf = (rates[0], None) if col_kinds[0] == "GAF" else (None, rates[0])
        elif page_kind:
            gaf, ldaf = (rates[0], None) if page_kind == "GAF" else (None, rates[0])
        elif len(rates) >= 2:
            gaf, ldaf = rates[0], rates[1]
        else:
            continue
        out.append({"label": label, "codes": codes, "gaf": gaf, "ldaf": ldaf,
                    "unit": "$/MDCQ Therms" if "mdcq" in low else "$/Therm"})
    return out


def read_pdf(name, data):
    import pdfplumber
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, p in enumerate(pdf.pages, 1):
            pages.append((i, (p.extract_text() or "").splitlines()))
    return pages


def analyse_pdf(name, data, month):
    """Returns dict(kind='page'|'filing', sections | rates, company)."""
    pages = read_pdf(name, data)
    full = "\n".join("\n".join(l) for _, l in pages)
    if SECTION_RE.search(full) and re.search(r"Rate Class\s+Billing Unit", full):
        return {"kind": "page", "sections": parse_page_text(full)}
    comp = company_key(name) or company_key(full[:4000])
    rates = []
    for pno, lines in pages:
        sch = extract_schedule(lines, month)
        if sch:
            rates.append({"Source": f"p.{pno} · {sch['class_line']}",
                          "Rate class (filing)": ", ".join(sorted(sch["codes"])),
                          "codes": sch["codes"], "Billing Unit": "$/Therm",
                          "GAF": sch["gaf"], "LDAF": sch["ldaf"],
                          "Block": sch["which"], "low_income": sch["low_income"]})
            continue
        for r in extract_table_rows(lines):
            rates.append({"Source": f"p.{pno} · {r['label'][:60]}",
                          "Rate class (filing)": r["label"][:60], "codes": r["codes"],
                          "Billing Unit": r["unit"], "GAF": r["gaf"], "LDAF": r["ldaf"],
                          "Block": "table", "low_income": "low income" in r["label"].lower()})
    return {"kind": "filing", "company": comp, "rates": rates, "pages": len(pages)}


# ---------------------------------------------------------------------------
# Matching filing rates to the page's rate-class rows
# ---------------------------------------------------------------------------

def match_rate(row, rates):
    """Pick the filing rate for one page row. Returns (rate, note)."""
    rc = row["Rate Class"]
    codes = class_codes(rc)
    unit_mdcq = "mdcq" in row["Billing Unit"].lower()
    pool = [r for r in rates if ("mdcq" in r["Billing Unit"].lower()) == unit_mdcq]
    cls = sorted(c for c in codes if re.match(r"[RGT]-\d", c))
    if cls:
        # first listed class (R-1 for "R-1, R-2", R-3 for "R-3, R-4") wins
        for c in cls:
            hit = [r for r in pool if c in r["codes"]]
            if hit:
                others = [r for r in pool if r["codes"] & set(cls) and r not in hit]
                note = ""
                for o in others:
                    if (o["GAF"], o["LDAF"]) != (hit[0]["GAF"], hit[0]["LDAF"]):
                        note = (f"{', '.join(sorted(o['codes'] & set(cls)))} differs in the "
                                f"filing (GAF {fmt_rate(o['GAF'])}, LDAF {fmt_rate(o['LDAF'])})")
                return hit[0], note
        return None, ""
    if "RES" in codes or "RES-H" in codes:        # "All Residential"
        for want in ("R-3", "RES-H", "RES", "R-1", "RES-NH"):
            hit = [r for r in pool if want in r["codes"] and not r["low_income"]]
            if hit:
                return hit[0], ("" if want in ("R-3", "RES-H", "RES") else
                                f"used {want} — no residential heating rate in the filing")
    if "RES-NH" in codes:
        hit = [r for r in pool if r["codes"] & {"R-1", "RES-NH"}]
        if hit:
            return hit[0], ""
    return None, ""


# ---------------------------------------------------------------------------
# Section building / exports
# ---------------------------------------------------------------------------

def season_for(d):
    if d.month >= 11:
        return "Peak/Winter", f"{d.year}-{d.year + 1}"
    if d.month <= 4:
        return "Peak/Winter", f"{d.year - 1}-{d.year}"
    return "Off-Peak/Summer", str(d.year)


def suggest_next(base):
    start = (base["end"] + timedelta(days=1)) if base.get("end") else date.today()
    season, yr = season_for(start)
    rev = (base["rev"] + 1) if (season == base.get("season") and yr == base.get("yr")) else 0
    end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    return season, yr, rev, start, end


def build_title(season, yr, rev, start, end):
    t = f"{season} {yr} Rates"
    if rev:
        t += f" Revision {rev}"
    return t + f" (Effective {mdy(start)} through {mdy(end)})"


def rows_df(rows):
    return pd.DataFrame(rows, columns=HEADER).astype(
        {"Rate Class": "string", "Billing Unit": "string",
         "GAF": "float64", "LDAF": "float64"})


def df_to_rows(df):
    out = []
    for r in df.to_dict("records"):
        rc = "" if pd.isna(r["Rate Class"]) else str(r["Rate Class"])
        if not rc.strip() and pd.isna(r["GAF"]) and pd.isna(r["LDAF"]):
            continue
        out.append({"Rate Class": rc,
                    "Billing Unit": "" if pd.isna(r["Billing Unit"]) else str(r["Billing Unit"]),
                    "GAF": None if pd.isna(r["GAF"]) else float(r["GAF"]),
                    "LDAF": None if pd.isna(r["LDAF"]) else float(r["LDAF"])})
    return out


def same_rows(a, b):
    if len(a) != len(b):
        return False
    return all(fmt_rate(x[k]) == fmt_rate(y[k]) if k in ("GAF", "LDAF")
               else str(x[k]).strip() == str(y[k]).strip()
               for x, y in zip(a, b) for k in HEADER)


def to_text(sec, repeat_header=True):
    hdr = "\t".join(HEADER)
    out = [sec["title"]]
    for c in sec["companies"]:
        out.append(c["name"] + ("REVISED" if c["revised"] else ""))
        out += c["notes"]
        out.append(hdr)
        for r in c["rows"]:
            out.append("\t".join([r["Rate Class"], r["Billing Unit"],
                                  fmt_rate(r["GAF"]), fmt_rate(r["LDAF"])]))
        if repeat_header:
            out.append(hdr)
    return "\n".join(out) + "\n"


def to_html(sec):
    e = htmlmod.escape
    out = [f"<h2>{e(sec['title'])}</h2>"]
    for c in sec["companies"]:
        badge = " <strong>REVISED</strong>" if c["revised"] else ""
        out.append(f"<h3>{e(c['name'])}{badge}</h3>")
        out += [f"<p>{e(n)}</p>" for n in c["notes"]]
        out.append("<table>\n  <thead><tr>" + "".join(f"<th>{h}</th>" for h in HEADER)
                   + "</tr></thead>\n  <tbody>")
        for r in c["rows"]:
            out.append("    <tr>" + "".join(f"<td>{e(v)}</td>" for v in (
                r["Rate Class"], r["Billing Unit"], fmt_rate(r["GAF"]),
                fmt_rate(r["LDAF"]))) + "</tr>")
        out.append("  </tbody>\n</table>")
    return "\n".join(out) + "\n"


def to_long(sec):
    return pd.DataFrame([{
        "Section": sec["title"], "Company": c["name"],
        "REVISED": "Yes" if c["revised"] else "", "Rate Class": r["Rate Class"],
        "Billing Unit": r["Billing Unit"], "GAF": fmt_rate(r["GAF"]),
        "LDAF": fmt_rate(r["LDAF"]), "Note": " ".join(c["notes"])}
        for c in sec["companies"] for r in c["rows"]])


SRC_LABEL = {"filing": "From filing", "shared": "Shared GAF (follows a class in the filing)",
             "edited": "Edited by hand", "carried": "Carried forward (not updated)", "": ""}
CARRIED_HTML = "#fff3b0"
CARRIED_XL = "FFF2CC"


def cell_src(c, i, f):
    src = c.get("src") or []
    return src[i].get(f, "") if i < len(src) else ""


def carried_count(sec):
    n = tot = 0
    for c in sec["companies"]:
        for i, r in enumerate(c["rows"]):
            for f in ("GAF", "LDAF"):
                if r[f] is not None:
                    tot += 1
                    n += cell_src(c, i, f) == "carried"
    return n, tot


def to_excel(sec):
    """One sheet laid out like the webpage, plus a flat table sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Webpage layout"
    blue = PatternFill("solid", fgColor="14558F")
    thin = Side(style="thin", color="D9D9D9")
    r = 1
    ws.cell(r, 1, sec["title"]).font = Font(bold=True, size=14, color="14558F")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    r += 1
    yellow = PatternFill("solid", fgColor=CARRIED_XL)
    n_car, n_tot = carried_count(sec)
    leg = ws.cell(r, 1, f"Highlighted = carried forward from {sec.get('base_title', 'the last posted section')}"
                        f" and not updated by any filing ({n_car} of {n_tot} values). "
                        "Check these before posting.")
    leg.fill = yellow
    leg.font = Font(italic=True, size=9)
    leg.alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    ws.row_dimensions[r].height = 28
    r += 2
    for c in sec["companies"]:
        ws.cell(r, 1, c["name"]).font = Font(bold=True, size=12)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        if c["revised"]:
            ws.cell(r, 5, "REVISED").font = Font(bold=True, color="CD0D0D")
        r += 1
        for n in c["notes"]:
            cell = ws.cell(r, 1, n)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.font = Font(italic=True)
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
            ws.row_dimensions[r].height = 15 * max(1, len(n) // 95 + 1)
            r += 1
        for j, h in enumerate(HEADER, 1):
            cell = ws.cell(r, j, h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = blue
        r += 1
        for ri, row in enumerate(c["rows"]):
            vals = [row["Rate Class"], row["Billing Unit"], row["GAF"], row["LDAF"]]
            for j, v in enumerate(vals, 1):
                cell = ws.cell(r, j, v)
                cell.border = Border(bottom=thin)
                if j >= 3:
                    cell.number_format = "0.0000"
                    cell.alignment = Alignment(horizontal="right")
                    if cell_src(c, ri, HEADER[j - 1]) == "carried":
                        cell.fill = yellow
            r += 1
        r += 1
    for j, w in enumerate([38, 16, 10, 10, 11], 1):
        ws.column_dimensions[get_column_letter(j)].width = w

    flat = wb.create_sheet("Table")
    cols = ["Section", "Company", "REVISED", "Rate Class", "Billing Unit", "GAF",
            "LDAF", "GAF source", "LDAF source", "Note"]
    flat.append(cols)
    for cell in flat[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = blue
    for c in sec["companies"]:
        for ri, row in enumerate(c["rows"]):
            gs, ls = cell_src(c, ri, "GAF"), cell_src(c, ri, "LDAF")
            flat.append([sec["title"], c["name"], "REVISED" if c["revised"] else "",
                         row["Rate Class"], row["Billing Unit"], row["GAF"], row["LDAF"],
                         SRC_LABEL[gs], SRC_LABEL[ls], " ".join(c["notes"])])
            xr = flat.max_row
            for col, sv in ((6, gs), (7, ls)):
                flat.cell(xr, col).number_format = "0.0000"
                if sv == "carried":
                    flat.cell(xr, col).fill = yellow
                    flat.cell(xr, col + 2).fill = yellow
    for j, w in enumerate([62, 50, 10, 34, 16, 10, 10, 30, 30, 60], 1):
        flat.column_dimensions[get_column_letter(j)].width = w
    flat.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def page_preview_html(sec):
    """Render the section the way it looks on mass.gov."""
    e = htmlmod.escape
    css = ("<style>.mg{font-family:'Noto Sans',Helvetica,Arial,sans-serif;color:#141414}"
           ".mg h2{font-size:1.6rem;font-weight:700;border-bottom:3px solid #14558f;"
           "padding-bottom:.3rem;margin:1rem 0}"
           ".mg h3{font-size:1.2rem;font-weight:700;margin:1.4rem 0 .4rem}"
           ".mg .rev{color:#cd0d0d;font-weight:700;margin-left:.4rem}"
           ".mg p{margin:.3rem 0 .6rem;line-height:1.5}"
           ".mg table{border-collapse:collapse;width:100%;margin-bottom:.8rem}"
           ".mg th{background:#14558f;color:#fff;text-align:left;padding:.5rem .7rem}"
           ".mg td{border-bottom:1px solid #d9d9d9;padding:.45rem .7rem}"
           ".mg tr:nth-child(even) td{background:#f2f2f2}"
           f".mg td.car{{background:{CARRIED_HTML}!important}}"
           f".mg .legend{{display:inline-block;background:{CARRIED_HTML};padding:.25rem .5rem;"
           "font-size:.85rem;margin-bottom:.5rem}</style>")
    n_car, n_tot = carried_count(sec)
    body = [f"<div class='mg'><h2>{e(sec['title'])}</h2>",
            f"<div class='legend'>Highlighted = carried forward from "
            f"{e(sec.get('base_title', 'the last posted section'))}, not updated by any "
            f"filing ({n_car} of {n_tot} values)</div>"]
    for c in sec["companies"]:
        rev = "<span class='rev'>REVISED</span>" if c["revised"] else ""
        body.append(f"<h3>{e(c['name'])}{rev}</h3>")
        body += [f"<p>{e(n)}</p>" for n in c["notes"]]
        body.append("<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in HEADER)
                    + "</tr></thead><tbody>")
        for ri, r in enumerate(c["rows"]):
            cells = [f"<td>{e(r['Rate Class'])}</td>", f"<td>{e(r['Billing Unit'])}</td>"]
            for f in ("GAF", "LDAF"):
                cls = " class='car'" if cell_src(c, ri, f) == "carried" else ""
                cells.append(f"<td{cls}>{e(fmt_rate(r[f]))}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        body.append("</tbody></table>")
    body.append("</div>")
    return css + "".join(body)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def massgov_page():
    ss = st.session_state
    ss.setdefault("mg_base", parse_page_text(DEFAULT_PAGE_TEXT)[0])
    ss.setdefault("mg_files", {})          # filename -> analysis
    ss.setdefault("mg_ver", 0)

    st.title("Mass.gov Rate Page — Gas Supply and Delivery Charges")
    st.caption("Created by Cathy Kam")

    # ---- 1. Drop PDFs ------------------------------------------------------
    st.subheader("1 · Drop PDFs")
    base = ss.mg_base
    s_season, s_yr, s_rev, s_start, s_end = suggest_next(base)
    files = st.file_uploader(
        "Drag and drop company rate filings (PDF). To update the starting layout, "
        "also drop a PDF of the mass.gov page (browser: Print → Save as PDF).",
        type=["pdf"], accept_multiple_files=True, key="mg_pdfs")

    with st.container(border=True):
        st.markdown("**New section**")
        g = st.columns([2, 1.2, 1, 1.3, 1.3])
        season = g[0].selectbox("Season", ["Peak/Winter", "Off-Peak/Summer"],
                                index=0 if s_season == "Peak/Winter" else 1,
                                key=f"mg_season_{base['title']}")
        yr = g[1].text_input("Year", s_yr, key=f"mg_yr_{base['title']}")
        rev = g[2].number_input("Revision (0 = none)", 0, 20, s_rev,
                                key=f"mg_rev_{base['title']}")
        start = g[3].date_input("Effective from", s_start, format="MM/DD/YYYY",
                                key=f"mg_start_{base['title']}")
        end = g[4].date_input("Through", s_end, format="MM/DD/YYYY",
                              key=f"mg_end_{base['title']}")
        title = build_title(season, yr, rev, start, end)
        st.markdown(f"**{title}**  \nStarting layout and carried-forward values: "
                    f"*{base['title']}*")
    month = MONTHS[start.month - 1]

    if files:
        for f in files:
            key = (f.name, f.size, month)
            if ss.mg_files.get(f.name, {}).get("key") != key:
                try:
                    res = analyse_pdf(f.name, f.getvalue(), month)
                except Exception as e:  # noqa: BLE001
                    res = {"kind": "error", "error": str(e)}
                res["key"] = key
                ss.mg_files[f.name] = res
                if res["kind"] == "page" and res["sections"]:
                    ss.mg_base = res["sections"][0]
                    ss.mg_ver += 1
                    st.rerun()
        for gone in set(ss.mg_files) - {f.name for f in files}:
            del ss.mg_files[gone]
    else:
        ss.mg_files = {}

    # ---- 2. Review what was pulled ---------------------------------------
    filings = {n: r for n, r in ss.mg_files.items() if r["kind"] == "filing"}
    for n, r in ss.mg_files.items():
        if r["kind"] == "page":
            st.success(f"{n}: read as the mass.gov page — {len(r['sections'])} "
                       f"section(s). Starting layout set to *{r['sections'][0]['title']}*.")
        elif r["kind"] == "error":
            st.error(f"{n}: could not read ({r['error']}).")

    names = [c["name"] for c in base["companies"]]
    keys = [company_key(c) for c in names]
    assigned = {}                          # company index -> list of rates
    if filings:
        st.subheader("2 · Rates pulled from the filings")
        st.caption(f"Monthly schedules are read for **{start:%B}** (the effective "
                   f"month). Proposed rates are used when the filing has them. "
                   f"Edit any value or untick a row to leave it out.")
        for fi, (fname, res) in enumerate(filings.items()):
            with st.container(border=True):
                c1, c2 = st.columns([3, 2])
                c1.markdown(f"**{fname}** · {res['pages']} page(s), "
                            f"{len(res['rates'])} rate row(s) found")
                guess = keys.index(res["company"]) if res["company"] in keys else None
                ci = c2.selectbox("Company on the page", range(len(names)),
                                  index=guess, format_func=lambda i: names[i],
                                  placeholder="Choose company…",
                                  key=f"mg_co_{fname}", label_visibility="collapsed")
                if not res["rates"]:
                    st.warning("No GAF/LDAF rates recognised in this PDF.")
                    continue
                df = pd.DataFrame([{"Use": True, **{k: r[k] for k in (
                    "Rate class (filing)", "Billing Unit", "GAF", "LDAF", "Block",
                    "Source")}} for r in res["rates"]])
                ed = st.data_editor(
                    df, hide_index=True, width="stretch", key=f"mg_rates_{fname}_{month}",
                    disabled=["Rate class (filing)", "Block", "Source"],
                    column_config={"GAF": st.column_config.NumberColumn(format="%.4f"),
                                   "LDAF": st.column_config.NumberColumn(format="%.4f")})
                if ci is None:
                    st.caption("Choose the company to use these rates.")
                    continue
                use = []
                for r, (_, e) in zip(res["rates"], ed.iterrows()):
                    if e["Use"]:
                        use.append({**r, "GAF": None if pd.isna(e["GAF"]) else e["GAF"],
                                    "LDAF": None if pd.isna(e["LDAF"]) else e["LDAF"],
                                    "Billing Unit": e["Billing Unit"]})
                assigned.setdefault(ci, []).extend(use)

    # ---- 3. Build the section --------------------------------------------
    st.subheader("3 · Section as it will appear on the webpage" if filings
                 else "2 · Section as it will appear on the webpage")
    spread = st.checkbox(
        "Apply a changed GAF to other rate classes that shared the same posted GAF "
        "(e.g. EGMA G-40 to G-43 follow R-3; G-50 to G-53 follow R-1)", True,
        key="mg_spread")
    companies, fill_log = [], []
    for ci, comp in enumerate(base["companies"]):
        c = copy.deepcopy(comp)
        c["revised"] = False
        matched, gaf_moves = set(), {}
        c["src"] = [{f: ("carried" if row[f] is not None else "") for f in ("GAF", "LDAF")}
                    for row in c["rows"]]
        for ri, row in enumerate(c["rows"]):
            hit, note = match_rate(row, assigned.get(ci, []))
            if hit:
                matched.add(ri)
                for f in ("GAF", "LDAF"):
                    if hit[f] is not None:
                        c["src"][ri][f] = "filing"
                if hit["GAF"] is not None and row["GAF"] is not None and \
                        "mdcq" not in row["Billing Unit"].lower():
                    gaf_moves.setdefault(fmt_rate(row["GAF"]), (round(float(hit["GAF"]), 4),
                                                                row["Rate Class"]))
            if hit:
                for f in ("GAF", "LDAF"):
                    if hit[f] is not None and fmt_rate(hit[f]) != fmt_rate(row[f]):
                        fill_log.append({"Company": c["name"], "Rate Class": row["Rate Class"],
                                         "Field": f, "Posted": fmt_rate(row[f]),
                                         "New": fmt_rate(hit[f]), "From": hit["Source"],
                                         "Note": note})
                        row[f] = round(float(hit[f]), 4)
                if note and not any(x["Note"] == note and x["Company"] == c["name"]
                                    for x in fill_log):
                    fill_log.append({"Company": c["name"], "Rate Class": row["Rate Class"],
                                     "Field": "", "Posted": "", "New": "", "From": hit["Source"],
                                     "Note": note})
        if spread:
            for ri, row in enumerate(c["rows"]):
                mv = gaf_moves.get(fmt_rate(row["GAF"]))
                if ri in matched or not mv or "mdcq" in row["Billing Unit"].lower():
                    continue
                new, src_cls = mv
                c["src"][ri]["GAF"] = "shared"
                if fmt_rate(new) != fmt_rate(row["GAF"]):
                    fill_log.append({"Company": c["name"], "Rate Class": row["Rate Class"],
                                     "Field": "GAF", "Posted": fmt_rate(row["GAF"]),
                                     "New": fmt_rate(new),
                                     "From": f"same GAF as {src_cls} on the posted page",
                                     "Note": ""})
                    row["GAF"] = new
        companies.append(c)
    unmatched = [n for i, n in enumerate(names) if i in assigned and not any(
        x["Company"] == n for x in fill_log)]
    if fill_log:
        st.markdown("**Filled from the filings**")
        st.dataframe(pd.DataFrame(fill_log), hide_index=True, width="stretch")
    for n in unmatched:
        st.info(f"{n}: the filing's rates match the posted values, or none of its "
                "rate classes matched a row on the page.")

    st.caption("Values not in any filing are carried forward from the starting layout. "
               "Fine-tune below; REVISED is set automatically for companies that changed.")
    final = []
    flag_opts = ["Auto", "Show", "Hide"]
    sig = str(sorted((k, v["key"]) for k, v in ss.mg_files.items()))
    for ci, c in enumerate(companies):
        posted = base["companies"][ci]["rows"]
        with st.expander(c["name"] + ("  ·  changed" if not same_rows(c["rows"], posted)
                                      else ""), expanded=False):
            ed = st.data_editor(rows_df(c["rows"]), num_rows="dynamic", hide_index=True,
                                width="stretch",
                                key=f"mg_ed_{ss.mg_ver}_{ci}_{hash(sig + month)}",
                                column_config={
                                    "GAF": st.column_config.NumberColumn(format="%.4f"),
                                    "LDAF": st.column_config.NumberColumn(format="%.4f")})
            rows = df_to_rows(ed)
            src = []
            for i, r in enumerate(rows):
                same_row = i < len(c["rows"]) and \
                    r["Rate Class"].strip() == c["rows"][i]["Rate Class"].strip()
                src.append({f: ("" if r[f] is None else
                                (c["src"][i][f] or "edited")
                                if same_row and fmt_rate(r[f]) == fmt_rate(c["rows"][i][f])
                                else "edited") for f in ("GAF", "LDAF")})
            notes = st.text_area("Note(s) under the heading (one per line)",
                                 "\n".join(c["notes"]), key=f"mg_note_{ss.mg_ver}_{ci}")
            changed = not same_rows(rows, posted)
            flag = st.radio("REVISED label", flag_opts, horizontal=True,
                            key=f"mg_flag_{ss.mg_ver}_{ci}",
                            help=f"Auto = {'Show' if changed else 'Hide'}")
        final.append({"name": c["name"], "notes": [n.strip() for n in notes.splitlines()
                                                   if n.strip()],
                      "rows": rows, "src": src,
                      "revised": changed if flag == "Auto" else flag == "Show"})

    sec = {"title": title, "companies": final, "base_title": base["title"]}
    n_car, n_tot = carried_count(sec)
    if n_car:
        st.warning(f"{n_car} of {n_tot} values are carried forward from "
                   f"*{base['title']}* and not updated by any filing — highlighted "
                   "in yellow below and in the Excel file.")
    else:
        st.success("Every value comes from a filing or was edited by hand.")
    with st.container(height=700):
        st.html(page_preview_html(sec))

    # ---- Export -----------------------------------------------------------
    st.subheader("Export")
    st.download_button(
        "Download Excel", to_excel(sec),
        file_name=f"massgov_rates_{start:%Y-%m-%d}.xlsx", type="primary",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("Sheet 'Webpage layout' follows the page: section title, company "
               "heading (REVISED beside it), note, then the Rate Class / Billing Unit "
               "/ GAF / LDAF table. Sheet 'Table' has the same data as one flat table "
               "with the source of each value. Carried-forward values are highlighted "
               "in yellow in both sheets.")
