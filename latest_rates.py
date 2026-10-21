"""
Pick the latest GAF and LDAF for each company from all R-3 scenario sections
found in the dropped filings, and compare every scenario / date against it.
Created by Cathy Kam.

Rules (most important first):
  * Alternative / illustrative scenarios (seasonal re-allocation, "Illustrative
    Rates", "Re-allocation") never set the latest rate; they fill the
    Alternative LDAF table instead.
  * A scenario only counts for a field if it actually proposes it
    (proposed value differs from its current value). An LDAC filing that holds
    the CGA constant does not propose a GAF.
  * GAF comes first from a CGAC (cost of gas) filing, LDAF first from an LDAC
    filing; then the most recently filed document; then "Revised" documents;
    then summary tables (Form IIA) over typical-bill pages.
"""

import re
from datetime import date, datetime

MONTHS = ("january february march april may june july august september "
          "october november december").split()
DATE_RE = r"(?:%s)\s+\d{1,2},\s*\d{4}" % "|".join(m.capitalize() for m in MONTHS)


def _d(s):
    try:
        return datetime.strptime(re.sub(r"\s+", " ", s.strip()), "%B %d, %Y").date()
    except ValueError:
        return None


def fmt(v):
    return "" if v is None else f"{float(v):.4f}"


# ---------------------------------------------------------------------------
# File metadata
# ---------------------------------------------------------------------------

def file_meta(fname, pages):
    """subject (CGAC/LDAC/None), revised, filed date, references to other
    filings' dates, and R-3 values from summary tables (Form IIA)."""
    head = fname + " " + " ".join(" ".join(l[:8]) for _, l in pages[:3])
    tag_re = r"\(\s*(LDAC|CGAC|CGCA)\s*\)|\b(LDAC|CGAC)\b"
    subject = None
    m = re.search(tag_re, fname.upper())            # the file name decides first
    if m:
        subject = (m.group(1) or m.group(2)).replace("CGCA", "CGAC")
    else:                                           # else the docket tag on most pages
        counts = {}
        for _, l in pages:
            for t in re.findall(r"PGAF-\w+\s*\(\s*(LDAC|CGAC|CGCA)\s*\)", " ".join(l[:6]).upper()):
                t = t.replace("CGCA", "CGAC")
                counts[t] = counts.get(t, 0) + 1
        if counts:
            subject = max(counts, key=counts.get)
    revised = bool(re.search(r"revised", head, re.I))
    full = "\n".join("\n".join(l) for _, l in pages)
    filed = [d for d in (_d(m) for m in re.findall(r"Filed:\s*(" + DATE_RE + ")", full)) if d]
    refs = {}
    for m in re.finditer(r"\(\s*(LDAC|CGAC)\s*\)\s*_?\s*(Revised)?\s+filed on\s+(" + DATE_RE + ")",
                         full, re.I):
        refs[(m.group(1).upper(), bool(m.group(2)))] = _d(m.group(3))
    summary = {}
    try:
        from massgov_page import extract_column_table
        for pno, lines in pages:
            if not re.search(r"Rate Schedule|R-1\s+R-2\s+R-3", "\n".join(lines[:40])):
                continue
            for r in extract_column_table(lines):
                if "R-3" not in r["codes"]:
                    continue
                if r["kind"] == "GAF" and re.search(r"off-?peak", r["label"], re.I):
                    continue
                summary.setdefault(r["kind"], (r["value"], f"{pno} ({r['label']})"))
    except Exception:  # noqa: BLE001
        pass
    return {"subject": subject, "revised": revised,
            "filed": max(filed) if filed else None, "refs": refs, "summary": summary}


def resolve_dates(metas):
    """Fill a missing filed date from another filing's reference, e.g. the
    CGAC filing saying '(LDAC)Revised filed on August 27, 2026'."""
    refs = {}
    for m in metas.values():
        refs.update(m["refs"])
    for m in metas.values():
        if m["filed"] is None and m["subject"]:
            m["filed"] = refs.get((m["subject"], m["revised"])) or refs.get((m["subject"], False))
            m["filed_inferred"] = m["filed"] is not None
    return metas


# ---------------------------------------------------------------------------
# Scenario classification
# ---------------------------------------------------------------------------

def is_alternative(sec):
    v, x = sec["values"], sec.get("extra", {})
    text = " ".join([sec.get("proposed_basis", ""), sec.get("compared_line", ""),
                     " ".join(sec.get("title", [])), sec.get("page_text", "")[-600:]])
    if re.search(r"re-?allocation|alternative|illustrative rates effective", text, re.I):
        return True
    if re.match(r"\s*illustrative", sec.get("proposed_basis", ""), re.I):
        return True
    p, po = v.get("prop_ldaf"), x.get("prop_ldaf_offpeak")
    c, co = v.get("cur_ldaf"), x.get("cur_ldaf_offpeak")
    # proposed LDAF split by season while the current one is not
    return (p is not None and po is not None and abs(p - po) > 0.05
            and (c is None or co is None or abs(c - co) < 0.05 or abs(p - po) > 3 * abs(c - co)))


def basis_flags(sec):
    b = sec.get("current_basis", "")
    nov = re.search(r"(?:peak\s+)?LDAF effective November 1", b, re.I)
    may = re.search(r"(?:off-?peak\s+)?LDAF effective May 1", b, re.I)
    avg = re.search(r"average", b, re.I)
    return {"ldaf_nov": bool(nov), "ldaf_may": bool(may) and not nov, "gaf_avg": bool(avg),
            "offpeak_listed": bool(re.search(r"off-?peak LDAF effective", b, re.I))}


def section_label(sec):
    m = re.search(r"Section\s+\w+", " ".join(sec.get("title", [])) + " " + sec.get("name", ""))
    return m.group(0) if m else sec.get("page", "")


# ---------------------------------------------------------------------------
# Latest values per company
# ---------------------------------------------------------------------------

def resolve_company(secs, metas):
    out = {"chart": {}, "ldaf_tbl": {}, "alt": {}, "sources": {}, "compare": [],
           "notes": []}
    regular = [s for s in secs if not is_alternative(s)]
    alts = [s for s in secs if is_alternative(s)]

    def score(s_or_meta, field, summary=False):
        m = metas.get(s_or_meta["file"], {}) if isinstance(s_or_meta, dict) else {}
        subj = m.get("subject")
        want = "CGAC" if field == "GAF" else "LDAC"
        return (subj == want, m.get("filed") or date.min, m.get("revised", False), summary)

    latest = {}
    for field, pk, ck in (("GAF", "prop_gaf", "prior_gaf"), ("LDAF", "prop_ldaf", "cur_ldaf")):
        cands = []
        for s in regular:
            v = s["values"]
            if v.get(pk) is None:
                continue
            proposes = v.get(ck) is None or fmt(v[pk]) != fmt(v[ck])
            if proposes:
                cands.append((score(s, field), v[pk], f"{s['file']} · {section_label(s)} "
                              f"({s['page']})"))
        for fname in {s["file"] for s in secs}:
            sm = metas.get(fname, {}).get("summary", {}).get(field)
            if sm:
                cands.append((score({"file": fname}, field, True), sm[0],
                              f"{fname} · summary table {sm[1]}"))
        if cands:
            best = max(cands, key=lambda c: c[0])
            latest[field] = best[1]
            out["sources"][field] = best[2]
            others = sorted({fmt(c[1]) for c in cands} - {fmt(best[1])})
            if others:
                out["notes"].append(f"Other proposed {field} values in the filings: "
                                    f"{', '.join(others)} (latest used: {fmt(best[1])}).")

    ch = out["chart"]
    if "GAF" in latest:
        ch["prop_gaf"] = round(latest["GAF"], 4)
    if "LDAF" in latest:
        out["ldaf_tbl"]["prop_ldaf"] = round(latest["LDAF"], 4)

    # prior average GAF: a basis that says the CGA is an average, CGAC first
    pri = [s for s in regular if basis_flags(s)["gaf_avg"] and s["values"].get("prior_gaf")]
    pri.sort(key=lambda s: score(s, "GAF"), reverse=True)
    if pri:
        ch["prior_gaf"] = pri[0]["values"]["prior_gaf"]
        out["sources"]["prior_gaf"] = f"{pri[0]['file']} · {section_label(pri[0])}: " \
                                      f"{pri[0]['current_basis'][:80]}"
    # 11/1 LDAF (current peak) and off-peak LDAF
    nov = [s for s in secs if basis_flags(s)["ldaf_nov"] and s["values"].get("cur_ldaf")]
    nov.sort(key=lambda s: score(s, "LDAF"), reverse=True)
    if nov:
        out["ldaf_tbl"]["cur_ldaf"] = nov[0]["values"]["cur_ldaf"]
        out["sources"]["cur_ldaf"] = f"{nov[0]['file']} · {section_label(nov[0])}"
    offp = [(s, s.get("extra", {}).get("cur_ldaf_offpeak")) for s in secs
            if basis_flags(s)["offpeak_listed"]]
    offp += [(s, s["values"].get("cur_ldaf")) for s in secs if basis_flags(s)["ldaf_may"]]
    offp = [(s, v) for s, v in offp if v is not None]
    offp.sort(key=lambda t: score(t[0], "LDAF"), reverse=True)
    if offp:
        out["ldaf_tbl"]["offpeak_ldaf"] = offp[0][1]
        out["sources"]["offpeak_ldaf"] = f"{offp[0][0]['file']} · {section_label(offp[0][0])}"

    # bills: the scenario that matches the latest GAF and LDAF, against the
    # average prior GAF and the 11/1 LDAF (only GAF + LDAF change)
    def bill_score(s):
        v, b = s["values"], basis_flags(s)
        return ((2 if "GAF" in latest and fmt(v.get("prop_gaf")) == fmt(latest["GAF"]) else 0)
                + (2 if "LDAF" in latest and fmt(v.get("prop_ldaf")) == fmt(latest["LDAF"]) else 0)
                + b["gaf_avg"] + b["ldaf_nov"]
                - (1 if re.search(r"all-?in|all rates", s.get("compared_line", ""), re.I) else 0),
                score(s, "GAF"))
    billable = [s for s in regular if s["values"].get("prior_bill") is not None]
    if billable:
        bs = max(billable, key=bill_score)
        for k in ("usage", "prior_bill", "prop_bill"):
            if bs["values"].get(k) is not None:
                ch[k] = bs["values"][k]
        for k in ("prior_winter_bill", "prop_winter_bill"):
            if bs["values"].get(k) is not None:
                out["ldaf_tbl"][k] = bs["values"][k]
        out["bill_section"] = bs
        out["sources"]["bills"] = f"{bs['file']} · {section_label(bs)} ({bs['page']}): " \
                                  f"{bs.get('compared_line') or bs['proposed_basis']}"
    if "usage" not in ch:
        u = next((s["values"]["usage"] for s in secs if s["values"].get("usage")), None)
        if u:
            ch["usage"] = u

    # alternative LDAF table
    if alts:
        alts.sort(key=lambda s: (score(s, "LDAF"), basis_flags(s)["ldaf_nov"]), reverse=True)
        a = alts[0]
        x = a.get("extra", {})
        out["alt"] = {"cur_ldaf": out["ldaf_tbl"].get("cur_ldaf"),
                      "offpeak_ldaf": out["ldaf_tbl"].get("offpeak_ldaf"),
                      "alt_peak_ldaf": a["values"].get("prop_ldaf"),
                      "alt_offpeak_ldaf": x.get("prop_ldaf_offpeak"),
                      "usage_offpeak": x.get("usage_offpeak")}
        out["sources"]["alt"] = f"{a['file']} · {section_label(a)} ({a['page']}): " \
                                f"{a.get('compared_line') or a['proposed_basis']}"

    # comparison of every scenario
    for s in secs:
        v, x, m = s["values"], s.get("extra", {}), metas.get(s["file"], {})
        alt = is_alternative(s)
        flags = []
        if not alt and "GAF" in latest and v.get("prop_gaf") is not None \
                and fmt(v["prop_gaf"]) != fmt(latest["GAF"]):
            flags.append("GAF ≠ latest" + (" (not proposed here)" if fmt(v.get("prop_gaf")) ==
                                           fmt(v.get("prior_gaf")) else ""))
        if not alt and "LDAF" in latest and v.get("prop_ldaf") is not None \
                and fmt(v["prop_ldaf"]) != fmt(latest["LDAF"]):
            flags.append("LDAF ≠ latest" + (" (not proposed here)" if fmt(v.get("prop_ldaf")) ==
                                            fmt(v.get("cur_ldaf")) else ""))
        used = []
        if out.get("bill_section") is s:
            used.append("bills")
        if alt and out["alt"] and out["sources"].get("alt", "").startswith(
                f"{s['file']} · {section_label(s)} ({s['page']})"):
            used.append("alternative LDAF")
        out["compare"].append({
            "File": s["file"],
            "Filed": (m["filed"].strftime("%m/%d/%Y") + (" (from reference)" if
                      m.get("filed_inferred") else "")) if m.get("filed") else "",
            "Section": section_label(s), "Page": s["page"],
            "Type": "Alternative / illustrative" if alt else "Proposed",
            "Compared from": s.get("current_basis", ""),
            "Compared to": s.get("compared_line") or s.get("proposed_basis", ""),
            "GAF": f"{fmt(v.get('prior_gaf'))} → {fmt(v.get('prop_gaf'))}",
            "LDAF (peak)": f"{fmt(v.get('cur_ldaf'))} → {fmt(v.get('prop_ldaf'))}",
            "LDAF (off-peak)": (f"{fmt(x.get('cur_ldaf_offpeak'))} → "
                                f"{fmt(x.get('prop_ldaf_offpeak'))}"),
            "Monthly bill": (f"${v['prior_bill']:,.2f} → ${v['prop_bill']:,.2f}"
                             if v.get("prior_bill") is not None and v.get("prop_bill") is not None
                             else ""),
            "Check": "; ".join(flags), "Used for": ", ".join(used)})
    out["latest"] = latest
    return out
