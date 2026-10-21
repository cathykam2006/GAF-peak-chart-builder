"""
Mass.gov rate page builder
--------------------------
Second page of the GAF Peak Chart Builder.  Created by Cathy Kam.

* Pulls the posted GAF/LDAF tables from
  https://www.mass.gov/info-details/information-on-gas-supply-and-delivery-charges
  (live, from a saved copy of the page, or from pasted page text).
* Starts the next revision from any posted section, with the next title and
  effective dates suggested.
* Fills new values from the Peak chart Parts (R-3 proposed GAF / LDAF) or by
  hand, flags changed companies as REVISED automatically.
* Exports in the page's format: plain text, HTML for the web editor, CSV.
"""

import calendar
import copy
import html as htmlmod
import re
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

PAGE_URL = ("https://www.mass.gov/info-details/"
            "information-on-gas-supply-and-delivery-charges")
HEADER = ["Rate Class", "Billing Unit", "GAF", "LDAF"]

SECTION_RE = re.compile(
    r"(?P<season>Peak/Winter|Off-Peak/Summer)\s+(?P<yr>\d{4}(?:\s*-\s*\d{4})?)\s+"
    r"Rates(?:\s+Revision\s+(?P<rev>\d+))?\s*\(\s*Effective\s+(?P<start>[\d/]+)"
    r"\s+(?:through|to|-)\s+(?P<end>[\d/]+)\s*\)", re.I)
HEADER_RE = re.compile(r"^\s*Rate Class\s+Billing Unit\s+GAF\s+LDAF\s*$", re.I)
ROW_RE = re.compile(r"^(?P<cls>.+?)\s+(?P<unit>\$/\s?[A-Za-z]+(?:\s+Therms)?)"
                    r"(?:\s+(?P<gaf>-?\d*\.\d+|-?\d+))?(?:\s+(?P<ldaf>-?\d*\.\d+|-?\d+))?\s*$")
REVISED_RE = re.compile(r"\s*REVISED\s*$")

# keyword -> how the company appears on the mass.gov page
COMPANY_KEYS = ["berkshire", "eversource gas company", "bay state", "fitchburg",
                "unitil", "blackstone", "north attleboro", "fall river",
                "boston gas", "colonial", "nstar"]

# Peak chart row -> keyword of the matching mass.gov company heading
PEAK_TO_SITE = {
    "Berkshire Gas": "berkshire",
    "EGMA": "eversource gas company",
    "Unitil (Fitchburg)": "fitchburg",
    "Blackstone": "blackstone",
    "Fall River/North Attleboro": "north attleboro",
    "Boston Gas": "boston gas",
    "former Colonial Gas": "colonial",
    "NSTAR Gas": "nstar",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return None if pd.isna(s) else float(s)
    t = str(s).strip().replace("$", "").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


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


def is_company_line(text):
    low = text.lower()
    return len(text) < 170 and any(k in low for k in COMPANY_KEYS)


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
    return {"name": REVISED_RE.sub(" ", heading).strip(),
            "revised": bool(re.search(r"REVISED", heading)),
            "notes": [], "notes_html": [], "rows": []}


def make_row(cells):
    cells = [c.strip() for c in cells] + [""] * 4
    return {"Rate Class": cells[0], "Billing Unit": cells[1],
            "GAF": to_num(cells[2]), "LDAF": to_num(cells[3])}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_html(page_html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page_html, "html.parser")
    sections, sec, comp = [], None, None
    for el in soup.find_all(["h2", "h3", "h4", "h5", "p", "table"]):
        if el.name != "table" and el.find_parent("table"):
            continue
        text = el.get_text(" ", strip=True)
        if el.name == "h2":
            if SECTION_RE.search(text):
                sec, comp = new_section(text), None
                sections.append(sec)
            else:
                sec, comp = None, None
            continue
        if sec is None:
            continue
        if el.name in ("h3", "h4", "h5") or (el.name == "p" and is_company_line(text)
                                               and (comp is None or comp["rows"])):
            if text:
                comp = new_company(text)
                sec["companies"].append(comp)
            continue
        if el.name == "p":
            if text and comp is not None:
                comp["notes"].append(text)
                comp["notes_html"].append(el.decode_contents().strip())
            continue
        if el.name == "table":
            if comp is None:
                comp = new_company("(company not named)")
                sec["companies"].append(comp)
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) < 2 or cells[0].lower() == "rate class":
                    continue
                comp["rows"].append(make_row(cells))
    return [s for s in sections if s["companies"]]


def parse_text(text):
    """Parse text copied from the page (the format in the user's example)."""
    sections, sec, comp = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or HEADER_RE.match(line.replace("\t", " ")):
            continue
        if SECTION_RE.search(line):
            sec, comp = new_section(line), None
            sections.append(sec)
            continue
        if sec is None:
            continue
        cells = [c for c in raw.split("\t")]
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
        elif is_company_line(line) and (comp is None or comp["rows"]
                                        or len(line) < 120):
            comp = new_company(line)
            sec["companies"].append(comp)
        elif comp is not None:
            comp["notes"].append(line)
            comp["notes_html"].append(htmlmod.escape(line))
    return [s for s in sections if s["companies"]]


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_page(url):
    import requests
    r = requests.get(url, timeout=30, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept-Language": "en-US,en;q=0.9"})
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Next-revision logic
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
    df = pd.DataFrame(rows, columns=HEADER)
    return df.astype({"Rate Class": "string", "Billing Unit": "string",
                      "GAF": "float64", "LDAF": "float64"})


def same_rows(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        for k in HEADER:
            vx, vy = x.get(k), y.get(k)
            if k in ("GAF", "LDAF"):
                nx = vx is None or pd.isna(vx)
                ny = vy is None or pd.isna(vy)
                if nx != ny or (not nx and abs(float(vx) - float(vy)) > 1e-9):
                    return False
            elif str(vx or "").strip() != str(vy or "").strip():
                return False
    return True


def df_to_rows(df):
    out = []
    for r in df.to_dict("records"):
        if not str(r.get("Rate Class") or "").strip() and r.get("GAF") is None:
            continue
        out.append({"Rate Class": "" if pd.isna(r["Rate Class"]) else str(r["Rate Class"]),
                    "Billing Unit": "" if pd.isna(r["Billing Unit"]) else str(r["Billing Unit"]),
                    "GAF": None if pd.isna(r["GAF"]) else float(r["GAF"]),
                    "LDAF": None if pd.isna(r["LDAF"]) else float(r["LDAF"])})
    return out


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

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
        badge = ' <strong>REVISED</strong>' if c["revised"] else ""
        out.append(f"<h3>{e(c['name'])}{badge}</h3>")
        for n in (c["notes_html"] or [e(n) for n in c["notes"]]):
            out.append(f"<p>{n}</p>")
        out.append("<table>\n  <thead><tr>" + "".join(f"<th>{h}</th>" for h in HEADER)
                   + "</tr></thead>\n  <tbody>")
        for r in c["rows"]:
            out.append("    <tr>" + "".join(f"<td>{e(v)}</td>" for v in (
                r["Rate Class"], r["Billing Unit"], fmt_rate(r["GAF"]),
                fmt_rate(r["LDAF"]))) + "</tr>")
        out.append("  </tbody>\n</table>")
    return "\n".join(out) + "\n"


def to_long(sections):
    recs = []
    for s in sections:
        for c in s["companies"]:
            for r in c["rows"]:
                recs.append({
                    "Section": s["title"],
                    "Effective from": mdy(s["start"]) if s.get("start") else "",
                    "Effective through": mdy(s["end"]) if s.get("end") else "",
                    "Company": c["name"], "REVISED": "Yes" if c["revised"] else "",
                    "Rate Class": r["Rate Class"], "Billing Unit": r["Billing Unit"],
                    "GAF": fmt_rate(r["GAF"]), "LDAF": fmt_rate(r["LDAF"]),
                    "Note": " ".join(c["notes"])})
    return pd.DataFrame(recs)


def show_section(sec):
    st.markdown(f"#### {sec['title']}")
    for c in sec["companies"]:
        badge = "  :red[**REVISED**]" if c["revised"] else ""
        st.markdown(f"**{c['name']}**{badge}")
        for n in c["notes"]:
            st.caption(n)
        show = pd.DataFrame([{**r, "GAF": fmt_rate(r["GAF"]), "LDAF": fmt_rate(r["LDAF"])}
                             for r in c["rows"]], columns=HEADER)
        st.dataframe(show, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Fill from Peak chart Parts
# ---------------------------------------------------------------------------

def heating_row_index(rows):
    for pat in (r"residential heating|\br-?3\b", r"all residential"):
        for i, r in enumerate(rows):
            if re.search(pat, r["Rate Class"], re.I):
                return i
    return None


def plan_from_part(part, companies, base_by_name, use_gaf, use_ldaf, spread_gaf,
                   colonial_uses_boston):
    peak = part["peak"].set_index("Company")
    ldaf = part["ldaf"].set_index("Company")
    changes = []
    for peak_name, key in PEAK_TO_SITE.items():
        comp = next((c for c in companies if key in c["name"].lower()), None)
        if comp is None or not comp["rows"]:
            continue
        idx = heating_row_index(comp["rows"])
        if idx is None:
            continue
        new_gaf = peak.at[peak_name, "prop_gaf"] if peak_name in peak.index else None
        if (new_gaf is None or pd.isna(new_gaf)) and colonial_uses_boston \
                and peak_name == "former Colonial Gas":
            new_gaf = peak.at["Boston Gas", "prop_gaf"]
        new_ldaf = ldaf.at[peak_name, "prop_ldaf"] if peak_name in ldaf.index else None
        hrow = comp["rows"][idx]
        old_gaf = hrow["GAF"]
        if use_gaf and new_gaf is not None and not pd.isna(new_gaf):
            new_gaf = round(float(new_gaf), 4)
            targets = [idx]
            if spread_gaf and old_gaf is not None:
                targets = [i for i, r in enumerate(comp["rows"])
                           if r["GAF"] is not None and abs(r["GAF"] - old_gaf) < 1e-9
                           and "therm" in r["Billing Unit"].lower()
                           and "mdcq" not in r["Billing Unit"].lower()]
            for i in targets:
                if comp["rows"][i]["GAF"] != new_gaf:
                    changes.append((comp["name"], i, "GAF", comp["rows"][i]["GAF"],
                                    new_gaf, peak_name))
        if use_ldaf and new_ldaf is not None and not pd.isna(new_ldaf):
            new_ldaf = round(float(new_ldaf), 4)
            if hrow["LDAF"] != new_ldaf:
                changes.append((comp["name"], idx, "LDAF", hrow["LDAF"], new_ldaf,
                                peak_name))
    return changes


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def massgov_page():
    ss = st.session_state
    ss.setdefault("mg_sections", [])
    ss.setdefault("mg_draft", None)
    ss.setdefault("mg_ver", 0)

    st.title("Mass.gov Rate Page — Gas Supply and Delivery Charges")
    st.caption("Created by Cathy Kam")

    # ---- 1. Pull posted rates --------------------------------------------
    st.subheader("1 · Pull the posted rates")
    c1, c2 = st.columns([4, 1])
    url = c1.text_input("Page URL", PAGE_URL, label_visibility="collapsed")
    if c2.button("Pull from mass.gov", type="primary"):
        try:
            with st.spinner("Reading mass.gov…"):
                secs = parse_html(fetch_page(url.split("#")[0]))
            if secs:
                ss.mg_sections = secs
                st.success(f"Found {len(secs)} rate sections.")
            else:
                st.error("The page loaded but no rate sections were recognised. "
                         "Use one of the options below.")
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not read mass.gov ({e}). The site sometimes blocks "
                     "automated requests — use one of the options below instead.")

    with st.expander("Other ways to load the page (if the pull is blocked)"):
        up = st.file_uploader("Drop a saved copy of the page (in your browser: "
                              "File → Save Page As… → Webpage, HTML only)",
                              type=["html", "htm"], key="mg_html")
        pasted = st.text_area("…or paste text copied from the page (select from a "
                              "section heading down through its tables)", height=150)
        if st.button("Load from file / pasted text"):
            secs = []
            if up is not None:
                secs = parse_html(up.getvalue().decode("utf-8", errors="ignore"))
            if not secs and pasted.strip():
                secs = parse_text(pasted)
            if secs:
                ss.mg_sections = secs
                st.success(f"Found {len(secs)} rate sections.")
            else:
                st.error("No rate sections recognised. Each section must start "
                         "with a heading like 'Off-Peak/Summer 2026 Rates Revision 3 "
                         "(Effective 10/1/26 through 10/31/26)'.")

    sections = ss.mg_sections
    if not sections:
        st.info("Pull the page to begin.")
        return

    titles = [s["title"] for s in sections]
    pick = st.selectbox("View a posted section", range(len(sections)),
                        format_func=lambda i: titles[i])
    with st.expander("Show section", expanded=False):
        show_section(sections[pick])
    d1, d2 = st.columns(2)
    d1.download_button("This section · CSV",
                       to_long([sections[pick]]).to_csv(index=False).encode("utf-8-sig"),
                       file_name="massgov_section.csv", mime="text/csv")
    d2.download_button("All posted sections · CSV (history)",
                       to_long(sections).to_csv(index=False).encode("utf-8-sig"),
                       file_name="massgov_all_sections.csv", mime="text/csv")

    # ---- 2. Start the next revision --------------------------------------
    st.subheader("2 · Start the next revision")
    base_i = st.selectbox("Start from (carried forward unless changed)",
                          range(len(sections)), format_func=lambda i: titles[i],
                          key="mg_base")
    base = sections[base_i]
    s_season, s_yr, s_rev, s_start, s_end = suggest_next(base)
    g = st.columns([2, 1.2, 1, 1.3, 1.3])
    season = g[0].selectbox("Season", ["Peak/Winter", "Off-Peak/Summer"],
                            index=0 if s_season == "Peak/Winter" else 1,
                            key=f"mg_season_{base_i}")
    yr = g[1].text_input("Year", s_yr, key=f"mg_yr_{base_i}")
    rev = g[2].number_input("Revision (0 = none)", 0, 20, s_rev, key=f"mg_rev_{base_i}")
    start = g[3].date_input("Effective from", s_start, key=f"mg_start_{base_i}",
                            format="MM/DD/YYYY")
    end = g[4].date_input("Through", s_end, key=f"mg_end_{base_i}",
                          format="MM/DD/YYYY")
    title = build_title(season, yr, rev, start, end)
    st.markdown(f"New section title: **{title}**")

    if st.button("Create draft from this base", type="primary"):
        comps = copy.deepcopy(base["companies"])
        for c in comps:
            c["revised"] = False
        ss.mg_draft = {"base_title": base["title"],
                       "base": {c["name"]: copy.deepcopy(c["rows"]) for c in comps},
                       "companies": comps, "rows_base": {c["name"]: c["rows"] for c in comps},
                       "flag": {c["name"]: "Auto" for c in comps}}
        ss.mg_ver += 1
        st.rerun()

    draft = ss.mg_draft
    if not draft:
        return
    draft["title"] = title
    st.caption(f"Draft carried forward from: {draft['base_title']}")

    # ---- 3. Fill in new values -------------------------------------------
    st.subheader("3 · Fill in new values")
    parts = ss.get("parts") or []
    with st.container(border=True):
        st.markdown("**From the Peak chart** — proposed R-3 GAF and LDAF go into each "
                    "company's residential heating row (or All Residential).")
        if not parts:
            st.caption("No Parts yet — build them on the Peak chart page first.")
        else:
            pi = st.selectbox("Part", range(len(parts)),
                              format_func=lambda i: parts[i]["name"], key="mg_part")
            o = st.columns(4)
            use_gaf = o[0].checkbox("Update GAF", True)
            use_ldaf = o[1].checkbox("Update LDAF", True)
            spread = o[2].checkbox("Apply new GAF to other classes that shared the "
                                   "old residential heating GAF", True,
                                   help="On the posted page the G-4x classes usually "
                                        "share the R-3 GAF. Rows with a different GAF "
                                        "(e.g. R-1/R-2, G-5x, MDCQ) are left alone.")
            colo = o[3].checkbox("Colonial uses Boston Gas GAF if blank", True)
            changes = plan_from_part(parts[pi], draft["companies"], draft["base"],
                                     use_gaf, use_ldaf, spread, colo)
            if changes:
                st.dataframe(pd.DataFrame([{
                    "Company": c, "Rate Class": next(
                        x for x in draft["companies"] if x["name"] == c)["rows"][i]["Rate Class"],
                    "Field": f, "Current": fmt_rate(old), "New": fmt_rate(new),
                    "From Peak chart row": src} for c, i, f, old, new, src in changes]),
                    hide_index=True, width="stretch")
                if st.button(f"Apply {len(changes)} change(s)", type="primary"):
                    for cname, i, f, _, new, _ in changes:
                        comp = next(x for x in draft["companies"] if x["name"] == cname)
                        comp["rows"][i][f] = new
                    draft["rows_base"] = {c["name"]: copy.deepcopy(c["rows"])
                                          for c in draft["companies"]}
                    ss.mg_ver += 1
                    st.rerun()
            else:
                st.caption("Nothing to change from this Part.")

    st.markdown("**Edit by company** — change any value, add or delete rows, edit "
                "notes. REVISED is set automatically when anything differs from the base.")
    for ci, comp in enumerate(draft["companies"]):
        name = comp["name"]
        base_rows = draft["base"].get(name, [])
        with st.expander(name + ("  ·  changed" if not same_rows(comp["rows"], base_rows)
                                 else ""), expanded=False):
            df = st.data_editor(
                rows_df(draft["rows_base"][name]), num_rows="dynamic", hide_index=True,
                width="stretch", key=f"mg_ed_{ss.mg_ver}_{ci}",
                column_config={
                    "GAF": st.column_config.NumberColumn(format="%.4f"),
                    "LDAF": st.column_config.NumberColumn(format="%.4f")})
            comp["rows"] = df_to_rows(df)
            notes = st.text_area("Note(s) under the heading (one per line)",
                                 "\n".join(comp["notes"]), key=f"mg_note_{ss.mg_ver}_{ci}")
            new_notes = [n.strip() for n in notes.splitlines() if n.strip()]
            if new_notes != comp["notes"]:
                comp["notes"] = new_notes
                comp["notes_html"] = [htmlmod.escape(n) for n in new_notes]
            changed = not same_rows(comp["rows"], base_rows)
            draft["flag"][name] = st.radio(
                "REVISED label", ["Auto", "Show", "Hide"],
                index=["Auto", "Show", "Hide"].index(draft["flag"].get(name, "Auto")),
                horizontal=True, key=f"mg_flag_{ss.mg_ver}_{ci}",
                help=f"Auto = {'Show' if changed else 'Hide'} (values "
                     f"{'differ from' if changed else 'match'} the base)")
        flag = draft["flag"][name]
        comp["revised"] = changed if flag == "Auto" else flag == "Show"

    # change summary
    diffs = []
    for comp in draft["companies"]:
        old = draft["base"].get(comp["name"], [])
        for i, r in enumerate(comp["rows"]):
            o = old[i] if i < len(old) else {}
            for f in ("GAF", "LDAF"):
                if fmt_rate(r[f]) != fmt_rate(o.get(f)):
                    diffs.append({"Company": comp["name"], "Rate Class": r["Rate Class"],
                                  "Field": f, "Posted": fmt_rate(o.get(f)),
                                  "New": fmt_rate(r[f])})
        if len(old) > len(comp["rows"]):
            diffs.append({"Company": comp["name"], "Rate Class": "(rows removed)",
                          "Field": "", "Posted": str(len(old)), "New": str(len(comp["rows"]))})
    st.markdown(f"**Changes vs. {draft['base_title']}**")
    if diffs:
        st.dataframe(pd.DataFrame(diffs), hide_index=True, width="stretch")
    else:
        st.caption("No changes yet — the draft matches the base.")

    # ---- 4. Preview & export ---------------------------------------------
    st.subheader("4 · Preview and export")
    sec = {"title": title, "companies": draft["companies"], "start": start, "end": end}
    with st.expander("Preview as it will appear", expanded=True):
        show_section(sec)
    rep = st.checkbox("Repeat the table header after each table (as text copied from "
                      "the site does)", True)
    text_out = to_text(sec, rep)
    html_out = to_html(sec)
    stamp = f"{start:%Y-%m-%d}"
    e1, e2, e3 = st.columns(3)
    e1.download_button("Text (page format)", text_out.encode("utf-8"),
                       file_name=f"massgov_rates_{stamp}.txt", mime="text/plain",
                       type="primary")
    e2.download_button("HTML (for the web editor)", html_out.encode("utf-8"),
                       file_name=f"massgov_rates_{stamp}.html", mime="text/html")
    e3.download_button("CSV", to_long([sec]).to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"massgov_rates_{stamp}.csv", mime="text/csv")
    with st.expander("Copy text"):
        st.code(text_out, language=None)
    with st.expander("Copy HTML"):
        st.code(html_out, language="html")
