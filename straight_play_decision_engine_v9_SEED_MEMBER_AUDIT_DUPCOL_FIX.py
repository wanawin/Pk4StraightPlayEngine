# straight_play_decision_engine_v8.py
# Reusable AABC straight-play companion app with live playlist + seed/member operational replay audit
# Build marker: STRAIGHT_DECISION_ENGINE_V9_SEED_MEMBER_AUDIT_DUPCOL_FIX__2026-06-14

from __future__ import annotations

import io
import itertools
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

BUILD_ID = "STRAIGHT_DECISION_ENGINE_V9_SEED_MEMBER_AUDIT_DUPCOL_FIX__2026-06-14"


def safe_front_col(df: pd.DataFrame, loc: int, name: str, value) -> pd.DataFrame:
    """Insert/overwrite a context column without crashing on duplicate names.
    Used only for audit/fired-rule detail output; does not change scoring logic.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    if name in out.columns:
        out[name] = value
        cols = [c for c in out.columns if c != name]
        cols.insert(min(loc, len(cols)), name)
        return out.loc[:, cols]
    out.insert(min(loc, len(out.columns)), name, value)
    return out
DEFAULT_RULE_DB = "straight_rule_database_CORE025_v1.csv"

# -------------------------
# Core utility functions
# -------------------------

def norm4(x: object) -> Optional[str]:
    if x is None:
        return None
    d = re.findall(r"\d", str(x))
    if len(d) < 4:
        return None
    return "".join(d[:4])


def norm_member(x: object) -> Optional[str]:
    r = norm4(x)
    if not r:
        return None
    return "".join(sorted(r))


def is_aabc_member(member: str) -> bool:
    if not member or len(member) != 4:
        return False
    c = Counter(member)
    return len(c) == 3 and sorted(c.values()) == [1, 1, 2]


def unique_perms(member: str) -> List[str]:
    member = norm_member(member) or str(member).zfill(4)
    return sorted(set("".join(p) for p in itertools.permutations(member)))


def family_from_member(member: str) -> str:
    return "".join(sorted(set(member)))


def vtrac_digit(d: int) -> int:
    return (d % 5) + 1


def mirror_digit(d: int) -> int:
    return (d + 5) % 10


def bucket_num(name: str, val: int, cuts: Sequence[int]) -> str:
    prev = None
    for c in cuts:
        if val <= c:
            if prev is None:
                return f"{name}_le{c}"
            return f"{name}_{prev+1}_{c}"
        prev = c
    return f"{name}_gt{cuts[-1]}"


def seed_features(seed: str, member: Optional[str] = None) -> Dict[str, object]:
    seed = norm4(seed) or "0000"
    ds = [int(x) for x in seed]
    cnt = Counter(ds)
    s = sum(ds)
    feats: Dict[str, object] = {}
    feats["seed"] = seed
    feats["sum"] = s
    feats["sum_bucket"] = bucket_num("sum", s, [8, 12, 16, 20, 24])
    feats["sum_mod10"] = s % 10
    feats["root"] = 9 if s % 9 == 0 else s % 9
    feats["spread"] = max(ds) - min(ds)
    feats["spread_bucket"] = bucket_num("spread", int(feats["spread"]), [2, 4, 6, 8])
    feats["unique"] = len(cnt)
    feats["unique_bucket"] = f"unique_{len(cnt)}"
    feats["max_rep"] = max(cnt.values())
    feats["has_repeat"] = int(max(cnt.values()) > 1)
    feats["structure"] = "".join(map(str, sorted(cnt.values(), reverse=True)))
    feats["even_count"] = sum(d % 2 == 0 for d in ds)
    feats["odd_count"] = 4 - int(feats["even_count"])
    feats["even_sum"] = int(s % 2 == 0)
    feats["high_count"] = sum(d >= 5 for d in ds)
    feats["low_count"] = 4 - int(feats["high_count"])
    feats["parity_pattern"] = "".join("E" if d % 2 == 0 else "O" for d in ds)
    feats["highlow_pattern"] = "".join("H" if d >= 5 else "L" for d in ds)
    feats["vtrac_pattern"] = "".join(str(vtrac_digit(d)) for d in ds)
    feats["sorted_seed"] = "".join(map(str, sorted(ds)))
    feats["first2"] = seed[:2]
    feats["mid2"] = seed[1:3]
    feats["last2"] = seed[2:]
    feats["first_last"] = seed[0] + seed[3]
    feats["first2_sum"] = ds[0] + ds[1]
    feats["mid2_sum"] = ds[1] + ds[2]
    feats["last2_sum"] = ds[2] + ds[3]
    feats["firstlast_sum"] = ds[0] + ds[3]
    for nm in ["first2_sum", "mid2_sum", "last2_sum", "firstlast_sum"]:
        feats[f"{nm}_bucket"] = bucket_num(nm, int(feats[nm]), [4, 8, 12, 16])
        feats[f"{nm}_parity"] = "E" if int(feats[nm]) % 2 == 0 else "O"
        feats[f"{nm}_high"] = int(int(feats[nm]) >= 10)
    for i, d in enumerate(ds, 1):
        feats[f"pos{i}"] = d
        feats[f"pos{i}_parity"] = "E" if d % 2 == 0 else "O"
        feats[f"pos{i}_hl"] = "H" if d >= 5 else "L"
        feats[f"pos{i}_v"] = vtrac_digit(d)
    for k in range(10):
        feats[f"has{k}"] = int(k in cnt)
        feats[f"no{k}"] = int(k not in cnt)
        feats[f"cnt{k}"] = cnt.get(k, 0)
        for i, d in enumerate(ds, 1):
            feats[f"pos{i}_is{k}"] = int(d == k)
            feats[f"pos{i}_not{k}"] = int(d != k)
    present_pairs = set()
    for i in range(4):
        for j in range(i + 1, 4):
            present_pairs.add("".join(sorted([str(ds[i]), str(ds[j])])))
    for a in range(10):
        for b in range(a, 10):
            tok = f"{a}{b}"
            feats[f"pair_{tok}"] = int(tok in present_pairs)
            feats[f"nopair_{tok}"] = int(tok not in present_pairs)
    mirror_pairs = 0
    plus1_pairs = 0
    for i in range(4):
        for j in range(i + 1, 4):
            if ds[j] == mirror_digit(ds[i]) or ds[i] == mirror_digit(ds[j]):
                mirror_pairs += 1
            if abs(ds[j] - ds[i]) == 1 or abs(ds[j] - ds[i]) == 9:
                plus1_pairs += 1
    feats["mirror_pairs"] = mirror_pairs
    feats["mirror_bucket"] = bucket_num("mirror", mirror_pairs, [0, 1, 2, 3])
    feats["plusminus1_pairs"] = plus1_pairs
    feats["plusminus1_bucket"] = bucket_num("pm1", plus1_pairs, [0, 1, 2, 3])

    # Target-member relationship features are generated dynamically so the same engine
    # can support 025, 389, and future AABC members.
    target_digits = sorted(set(norm_member(member) or ""))
    for k in target_digits:
        feats[f"target_has{k}"] = feats.get(f"has{k}", 0)
        feats[f"target_no{k}"] = feats.get(f"no{k}", 1)
    if target_digits:
        feats["target_digit_count"] = sum(cnt.get(int(k), 0) for k in target_digits)
        feats["target_digit_count_bucket"] = f"targetcnt_{feats['target_digit_count']}"
        for a, b in itertools.combinations(target_digits, 2):
            feats[f"has_{a}_{b}_pair"] = int(feats.get(f"has{a}", 0) and feats.get(f"has{b}", 0))
    return feats


def atom_set_for_seed(seed: str, member: str) -> set[str]:
    feats = seed_features(seed, member)
    atoms = set()
    for k, v in feats.items():
        if k == "seed":
            continue
        if pd.isna(v):
            continue
        atoms.add(f"{k}={v}")
    return atoms

# -------------------------
# File reading / normalization
# -------------------------


def parse_printable_playlist_text(text: str) -> pd.DataFrame:
    """Parse human-printable playlists that are also machine-readable.

    Supported formats:
      OLD v173 printable:
        1. Arkansas | Cash 4 Evening
           PLAY: 0255  (1 play)
           Running plays... | Fit: 30.43

      NEW compact printable/machine format:
        PLAY_DATE: 2026-06-13
        #  Stream                           Core  Member  Seed   Fit
        01 Wisconsin Pick 4 Evening         025   0255    6467   31.66

    For the compact format, the date is read once from the header so every row
    can stay short and printable. The output still has date/member/seed/fit
    fields for the straight engine.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    rows = []

    # Header date forms: PLAY_DATE:2026-06-13, PLAY DATE: 2026-06-13, Date=2026/06/13
    play_date = None
    for ln in lines[:20]:
        mdate = re.search(r"(?:PLAY[_ ]?DATE|DATE)\s*[:=]\s*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})", ln, re.I)
        if mdate:
            play_date = pd.to_datetime(mdate.group(1), errors="coerce")
            break

    # New compact rows: rownum + free stream text + core + member + optional seed + fit at end.
    # This intentionally captures the stream as everything before the core/member fields.
    compact_re = re.compile(
        r"^\s*(?P<rank>\d{1,3})[\.)]?\s+"
        r"(?P<stream>.*?)\s+"
        r"(?P<core>\d{3})\s+"
        r"(?P<member>\d{4})"
        r"(?:\s+(?P<seed>\d{4}|\d[- ]\d[- ]\d[- ]\d))?"
        r"(?:\s+(?P<fit>-?\d+(?:\.\d+)?))?\s*$"
    )
    compact_rows = []
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith(('#','-','=')):
            continue
        m = compact_re.match(ln)
        if not m:
            continue
        stream = (m.group('stream') or '').strip()
        # avoid parsing prose/header lines accidentally
        if len(stream) < 3 or stream.lower() in {'stream'}:
            continue
        member = norm_member(m.group('member'))
        if not member or not is_aabc_member(member):
            continue
        row = {
            'playlist_rank': int(m.group('rank')),
            'stream': stream,
            'state': stream,
            'game': '',
            'core': m.group('core'),
            'member': member,
            'seed': norm4(m.group('seed')) if m.group('seed') else None,
            'fit_score': m.group('fit') or '',
        }
        if play_date is not None and not pd.isna(play_date):
            row['play_date'] = play_date.date().isoformat()
        compact_rows.append(row)
    if compact_rows:
        return pd.DataFrame(compact_rows)

    # Old v173 two-line printable parser.
    current = {}
    item_re = re.compile(r"^\s*(\d+)\.\s*(.*?)\s*\|\s*(.*?)\s*$")
    play_re = re.compile(r"PLAY:\s*([0-9]{1,4})")
    fit_re = re.compile(r"Fit:\s*([-+]?\d+(?:\.\d+)?)")
    for ln in lines:
        m = item_re.match(ln)
        if m:
            if current and current.get("member"):
                if play_date is not None and not pd.isna(play_date):
                    current['play_date'] = play_date.date().isoformat()
                rows.append(current)
            current = {
                "playlist_rank": int(m.group(1)),
                "state": m.group(2).strip(),
                "game": m.group(3).strip(),
                "stream": f"{m.group(2).strip()} | {m.group(3).strip()}",
            }
            continue
        pm = play_re.search(ln)
        if pm and current is not None:
            current["member"] = norm_member(pm.group(1)) or pm.group(1).zfill(4)
            continue
        fm = fit_re.search(ln)
        if fm and current is not None:
            current["fit_score"] = fm.group(1)
    if current and current.get("member"):
        if play_date is not None and not pd.isna(play_date):
            current['play_date'] = play_date.date().isoformat()
        rows.append(current)
    return pd.DataFrame(rows)

def read_table_upload(uploaded_file) -> pd.DataFrame:
    name = getattr(uploaded_file, "name", "uploaded")
    raw = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    lower = name.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw), dtype=str)
    if lower.endswith(".tsv"):
        return pd.read_csv(io.BytesIO(raw), dtype=str, sep="\t")
    # TXT: first try the known printable playlist parser, then delimiter, then raw lines.
    text = raw.decode("utf-8", errors="replace")
    printable = parse_printable_playlist_text(text)
    if not printable.empty:
        return printable
    try:
        return pd.read_csv(io.StringIO(text), dtype=str, sep=None, engine="python")
    except Exception:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return pd.DataFrame({"raw_line": lines})



def parse_history_raw_lines_to_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Parse old no-header history TXT rows.

    Supported rows look like:
      Sat, Feb 21, 2026<TAB>Wisconsin<TAB>Pick 4 Midday<TAB>9-8-9-0
      Sat, Feb 21, 2026    Wisconsin    Pick 4 Midday    9-8-9-0, Fireball: 3

    The parser keeps only the first/base four result digits and ignores Wild Ball,
    Fireball, Superball, Sum It Up, etc.
    """
    if "raw_line" not in df.columns:
        return None
    rows = []
    date_pat = re.compile(r"^(?P<date>[A-Za-z]{3},\s+[A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s+(?P<rest>.*)$")
    # final field must contain base result like 9-8-9-0 or 9890; extras after comma are ignored
    result_pat = re.compile(r"(?P<result>\d\s*[- ]?\s*\d\s*[- ]?\s*\d\s*[- ]?\s*\d)")
    for raw in df["raw_line"].astype(str).tolist():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"\t+", line) if p.strip()]
        if len(parts) >= 4:
            date_s = parts[0]
            state = parts[1]
            game = parts[2]
            res_s = parts[3]
        else:
            m = date_pat.match(line)
            if not m:
                continue
            date_s = m.group("date")
            rest = m.group("rest")
            rm = list(result_pat.finditer(rest))
            if not rm:
                continue
            last = rm[-1]
            res_s = last.group("result")
            before = rest[:last.start()].strip(" \t,-")
            # Split state/game from the left by two or more spaces/tabs when possible.
            bg = [p.strip() for p in re.split(r"\s{2,}|\t+", before) if p.strip()]
            if len(bg) >= 2:
                state, game = bg[0], " ".join(bg[1:])
            else:
                # Fallback: unknown split; preserve as stream text.
                state, game = before, ""
        r4 = norm4(res_s)
        if not r4:
            continue
        rows.append({"date": date_s, "state": state, "game": game, "result4": r4, "stream": f"{state} | {game}".strip(" |")})
    if not rows:
        return None
    parsed = pd.DataFrame(rows)
    parsed["date"] = pd.to_datetime(parsed["date"], errors="coerce")
    parsed = parsed.dropna(subset=["date", "result4"]).copy()
    return parsed

def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    original_cols = list(out.columns)
    out.columns = [str(c).strip() for c in out.columns]

    # Old no-header TXT history sometimes arrives as one raw_line column.
    # Convert it to a normal date/state/game/result4 table before column detection.
    if set(out.columns) == {"raw_line"} or "raw_line" in out.columns:
        parsed = parse_history_raw_lines_to_df(out)
        if parsed is not None and not parsed.empty:
            out = parsed
            original_cols = list(out.columns)
            out.columns = [str(c).strip() for c in out.columns]

    # If pandas inferred the first history row as headers, recover by treating
    # the column names themselves plus rows as raw lines.
    if len(out.columns) == 1 and "raw_line" not in out.columns:
        col0 = out.columns[0]
        maybe = pd.DataFrame({"raw_line": [str(col0)] + out.iloc[:, 0].astype(str).tolist()})
        parsed = parse_history_raw_lines_to_df(maybe)
        if parsed is not None and not parsed.empty:
            out = parsed
            original_cols = list(out.columns)
            out.columns = [str(c).strip() for c in out.columns]

    lowmap = {c.lower().replace(" ", "").replace("_", ""): c for c in out.columns}

    def find_col(cands: List[str]) -> Optional[str]:
        for cand in cands:
            key = cand.lower().replace(" ", "").replace("_", "")
            if key in lowmap:
                return lowmap[key]
        for c in out.columns:
            cl = c.lower()
            if any(cand.lower() in cl for cand in cands):
                return c
        return None

    date_col = find_col(["Date", "DrawDate", "event_date"])
    r4_col = find_col(["Result4", "Result", "WinningNumber", "Number", "Draw"])
    stream_col = find_col(["StreamKey", "Stream", "stream_key"])
    state_col = find_col(["State", "Jurisdiction", "Lottery"])
    game_col = find_col(["Game", "DrawName"])

    if date_col is None or r4_col is None:
        raise ValueError(f"History needs a date column and result/result4 column. Found columns: {original_cols}")
    out["date"] = pd.to_datetime(out[date_col], errors="coerce")
    out["r4"] = out[r4_col].apply(norm4)
    if stream_col:
        out["stream"] = out[stream_col].astype(str).str.strip()
    elif state_col and game_col:
        out["stream"] = out[state_col].astype(str).str.strip() + " | " + out[game_col].astype(str).str.strip()
    else:
        out["stream"] = "GLOBAL"
    out = out.dropna(subset=["date", "r4"]).copy()
    out["member"] = out["r4"].apply(lambda x: "".join(sorted(x)))
    out = out.sort_values(["stream", "date"]).reset_index(drop=True)
    return out[["date", "stream", "r4", "member"]]


def normalize_playlist(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def detect_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    low = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace(" ", "").replace("_", "")
        if key in low:
            return low[key]
    for c in df.columns:
        cl = c.lower()
        if any(cand.lower() in cl for cand in candidates):
            return c
    return None

# -------------------------
# Rule database training / scoring
# -------------------------

def build_event_dataset_from_history(hist: pd.DataFrame, member: str) -> pd.DataFrame:
    member = norm_member(member) or member
    perms = unique_perms(member)
    rows = []
    for stream, g in hist.groupby("stream"):
        g = g.sort_values("date").reset_index(drop=True)
        for i in range(1, len(g)):
            win = str(g.loc[i, "r4"])
            if "".join(sorted(win)) != member:
                continue
            seed = str(g.loc[i - 1, "r4"])
            if win not in perms:
                continue
            feats = seed_features(seed, member)
            rows.append({
                "event_idx": len(rows),
                "event_date": g.loc[i, "date"],
                "stream": stream,
                "seed_date": g.loc[i - 1, "date"],
                "seed": seed,
                "member": member,
                "winning_perm": win,
                **feats,
            })
    ev = pd.DataFrame(rows)
    if ev.empty:
        return ev
    ev = ev.sort_values(["event_date", "stream", "seed"]).reset_index(drop=True)
    ev["event_idx"] = range(len(ev))
    return ev


def train_adaptive_gate_rules(
    ev: pd.DataFrame,
    member: str,
    train_cutoff: Optional[pd.Timestamp] = None,
    max_gate_size: int = 3,
    min_rule_pos: int = 2,
    max_outside: int = 1,
    top_atoms_per_gate: int = 45,
    max_rules_per_gate: int = 60,
) -> pd.DataFrame:
    if ev.empty:
        return pd.DataFrame()
    df = ev.copy()
    df["event_date_dt"] = pd.to_datetime(df["event_date"], errors="coerce")
    if train_cutoff is not None:
        df = df[df["event_date_dt"] <= pd.to_datetime(train_cutoff)].copy()
    df = df.reset_index(drop=True)
    if len(df) < max(6, min_rule_pos):
        return pd.DataFrame()
    perms = unique_perms(member)
    all_gates = []
    for r in range(1, max_gate_size + 1):
        all_gates.extend(list(itertools.combinations(perms, r)))
    exclude = {"event_idx", "event_date", "event_date_dt", "seed_date", "winning_perm", "stream", "seed", "member"}
    feat_cols = [c for c in df.columns if c not in exclude]

    def row_atoms(row) -> set[str]:
        ats = []
        for c in feat_cols:
            v = row[c]
            if pd.isna(v) or str(v) == "":
                continue
            ats.append(f"{c}={v}")
        return set(ats)

    row_atom_sets = [row_atoms(df.iloc[i]) for i in range(len(df))]
    atom_mask = defaultdict(int)
    for local_i, atoms in enumerate(row_atom_sets):
        bit = 1 << local_i
        for a in atoms:
            atom_mask[a] |= bit
    all_train_mask = (1 << len(df)) - 1
    perm_mask = {p: 0 for p in perms}
    for local_i, row in df.iterrows():
        perm = str(row["winning_perm"])
        if perm in perm_mask:
            perm_mask[perm] |= (1 << local_i)

    def bc(x: int) -> int:
        return x.bit_count()

    lib = []
    for gate in all_gates:
        pos_mask = 0
        for p in gate:
            pos_mask |= perm_mask.get(p, 0)
        pos_total = bc(pos_mask)
        if pos_total < min_rule_pos:
            continue
        neg_mask = all_train_mask ^ pos_mask
        candidates = []
        for atom, mask in atom_mask.items():
            ps = bc(mask & pos_mask)
            if ps < min_rule_pos:
                continue
            ns = bc(mask & neg_mask)
            pos_rate = ps / max(1, pos_total)
            neg_rate = ns / max(1, len(df) - pos_total)
            contrast = pos_rate - neg_rate
            if ns > max_outside and contrast < 0.25:
                continue
            score = (ps - 1.75 * ns) + 2.5 * contrast + 0.15 * pos_rate
            candidates.append((score, atom, mask, ps, ns, pos_rate, neg_rate))
        candidates = sorted(candidates, reverse=True)[:top_atoms_per_gate]
        rules = []

        def add_rule(atoms: Tuple[str, ...], mask: int):
            ps = bc(mask & pos_mask)
            ns = bc(mask & neg_mask)
            if ps < min_rule_pos or ns > max_outside:
                return
            pos_rate = ps / max(1, pos_total)
            purity = ps / (ps + ns) if ps + ns else 0.0
            spec = len(atoms)
            score = (purity * 5.0 + ps * 0.9 + pos_rate * 2.0 - ns * 2.2 + spec * 0.18 - len(gate) * 0.20)
            rules.append((score, atoms, ps, ns, purity, pos_rate))

        for _, a, m, *_ in candidates:
            add_rule((a,), m)
        for i in range(len(candidates)):
            a1, m1 = candidates[i][1], candidates[i][2]
            for j in range(i + 1, len(candidates)):
                a2, m2 = candidates[j][1], candidates[j][2]
                add_rule((a1, a2), m1 & m2)
        top3 = candidates[:22]
        for i in range(len(top3)):
            a1, m1 = top3[i][1], top3[i][2]
            for j in range(i + 1, len(top3)):
                a2, m2 = top3[j][1], top3[j][2]
                m12 = m1 & m2
                if bc(m12 & pos_mask) < min_rule_pos:
                    continue
                for k in range(j + 1, len(top3)):
                    a3, m3 = top3[k][1], top3[k][2]
                    add_rule((a1, a2, a3), m12 & m3)
        rules = sorted(rules, key=lambda x: x[0], reverse=True)[:max_rules_per_gate]
        for score, atoms, ps, ns, purity, pos_rate in rules:
            lib.append({
                "member": member,
                "gate_tuple": repr(tuple(gate)),
                "gate": "|".join(gate),
                "train_pos": ps,
                "train_out": ns,
                "purity": purity,
                "pos_rate": pos_rate,
                "rule_score": score,
                "atoms_str": " & ".join(atoms),
                "train_cutoff": str(pd.to_datetime(train_cutoff).date()) if train_cutoff is not None else "FULL_HISTORY",
                "rule_source": BUILD_ID,
            })
    return pd.DataFrame(lib)


def load_rule_db_from_upload(upload) -> pd.DataFrame:
    df = read_table_upload(upload)
    return normalize_rule_db(df)


def normalize_rule_db(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    if "member" not in out.columns:
        # Legacy single-member db. User can still use it after assigning in UI if needed.
        out["member"] = ""
    required = ["member", "gate", "atoms_str", "rule_score", "train_pos", "train_out", "purity", "pos_rate"]
    for c in required:
        if c not in out.columns:
            out[c] = ""
    for c in ["rule_score", "train_pos", "train_out", "purity", "pos_rate"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["member"] = out["member"].apply(lambda x: norm_member(x) or str(x).zfill(4) if str(x).strip() else "")
    out["gate"] = out["gate"].astype(str)
    out["atoms_str"] = out["atoms_str"].astype(str)
    return out


def score_member_seed(member: str, seed: str, rules: pd.DataFrame, top_n_gates: int = 6) -> Tuple[List[dict], pd.DataFrame]:
    member = norm_member(member) or str(member).zfill(4)
    perms = unique_perms(member)
    atoms = atom_set_for_seed(seed, member)
    sub = rules[rules["member"].eq(member)].copy()
    all_gates = []
    for r in (1, 2, 3):
        all_gates.extend(["|".join(g) for g in itertools.combinations(perms, r)])
    fired_rows = []
    if not sub.empty:
        for _, row in sub.iterrows():
            atom_str = str(row.get("atoms_str", ""))
            req = [a.strip() for a in atom_str.split("&") if a.strip()]
            if req and all(a in atoms for a in req):
                fired_rows.append(row.to_dict())
    fired_df = pd.DataFrame(fired_rows)
    scored = []
    if not fired_df.empty:
        for gate, g in fired_df.groupby("gate"):
            scores = sorted(pd.to_numeric(g["rule_score"], errors="coerce").fillna(0).tolist(), reverse=True)
            best = g.sort_values(["rule_score", "train_pos", "train_out"], ascending=[False, False, True]).iloc[0]
            agg = sum(scores[:3])
            # Prefer strong rule stacks and smaller gates if scores tie.
            gate_size = len(str(gate).split("|"))
            final_score = float(best["rule_score"]) * 1.6 + agg * 0.25 - 0.08 * gate_size
            scored.append({
                "gate": gate,
                "gate_size": gate_size,
                "score": final_score,
                "rule_count": len(g),
                "best_rule": str(best.get("atoms_str", "")),
                "best_rule_score": float(best.get("rule_score", 0)),
                "best_train_pos": int(best.get("train_pos", 0)),
                "best_train_out": int(best.get("train_out", 0)),
            })
    # Add fallback gates with frequency-neutral score so output is never empty.
    existing = {s["gate"] for s in scored}
    for gate in all_gates:
        if gate not in existing:
            scored.append({"gate": gate, "gate_size": len(gate.split("|")), "score": -999 - 0.1 * len(gate.split("|")), "rule_count": 0, "best_rule": "NO_RULE_FIRED", "best_rule_score": 0, "best_train_pos": 0, "best_train_out": 0})
    scored = sorted(scored, key=lambda x: (x["score"], x["rule_count"], -x["gate_size"]), reverse=True)
    return scored[:top_n_gates], fired_df


def candidates_from_top_gates(scored: List[dict], n: int) -> List[str]:
    seen: List[str] = []
    for g in scored[:n]:
        for p in str(g["gate"]).split("|"):
            if p and p not in seen:
                seen.append(p)
    return seen


def history_frequency_order(hist: pd.DataFrame, member: str, train_cutoff: Optional[pd.Timestamp] = None) -> List[str]:
    ev = build_event_dataset_from_history(hist, member)
    if ev.empty:
        return unique_perms(member)
    if train_cutoff is not None:
        ev = ev[pd.to_datetime(ev["event_date"]) <= pd.to_datetime(train_cutoff)]
    vc = ev["winning_perm"].value_counts().to_dict()
    perms = unique_perms(member)
    return sorted(perms, key=lambda p: (-vc.get(p, 0), p))




def infer_default_train_cutoff(hist: pd.DataFrame) -> pd.Timestamp:
    """Choose a safe default training cutoff without requiring user input.

    Preferred locked project cutoff is 2026-02-20 when available. Otherwise use
    an 80% chronological split, leaving the newest ~20% as future/unseen test.
    """
    if hist is None or hist.empty or 'date' not in hist.columns:
        return pd.Timestamp('2026-02-20')
    dates = sorted(pd.to_datetime(hist['date'], errors='coerce').dropna().dt.normalize().unique())
    if not dates:
        return pd.Timestamp('2026-02-20')
    preferred = pd.Timestamp('2026-02-20')
    if pd.Timestamp(dates[0]) <= preferred <= pd.Timestamp(dates[-1]):
        return preferred
    if len(dates) < 5:
        return pd.Timestamp(dates[max(0, len(dates)-2)])
    idx = max(0, min(len(dates)-2, int(len(dates) * 0.80)))
    return pd.Timestamp(dates[idx])


def train_cutoff_safe_rules_for_members(hist: pd.DataFrame, members: Sequence[str], train_cutoff: pd.Timestamp, max_gate_size: int = 3, min_rule_pos: int = 2) -> pd.DataFrame:
    """Train a temporary, cutoff-safe rule database for backtesting.

    This deliberately ignores any uploaded/full-history rule DB so the test set
    cannot leak into rule generation.
    """
    dfs = []
    for m in members:
        nm = norm_member(m)
        if not nm or not is_aabc_member(nm):
            continue
        ev = build_event_dataset_from_history(hist, nm)
        lib = train_adaptive_gate_rules(ev, nm, pd.to_datetime(train_cutoff), max_gate_size=max_gate_size, min_rule_pos=min_rule_pos)
        if not lib.empty:
            dfs.append(lib)
    if not dfs:
        return pd.DataFrame()
    out = pd.concat(dfs, ignore_index=True)
    out = out.drop_duplicates(subset=['member','gate','atoms_str','train_cutoff'], keep='last')
    return normalize_rule_db(out)
def find_seed_from_history(hist: pd.DataFrame, stream: str, play_date: Optional[pd.Timestamp]) -> Optional[str]:
    if hist is None or hist.empty or not stream:
        return None
    h = hist[hist["stream"].astype(str).eq(str(stream))].copy()
    if h.empty:
        return None
    if play_date is not None and not pd.isna(play_date):
        h = h[h["date"] < pd.to_datetime(play_date)]
    if h.empty:
        return None
    return str(h.sort_values("date").iloc[-1]["r4"])



def backtest_truth_member(
    hist: pd.DataFrame,
    rules: pd.DataFrame,
    family: str,
    members: Sequence[str],
    train_cutoff: pd.Timestamp,
    test_start: Optional[pd.Timestamp] = None,
    test_end: Optional[pd.Timestamp] = None,
    top_gate_levels: Sequence[int] = (1, 2, 3),
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Historical straight-layer test assuming the boxed member is known/correct.

    This does NOT test the member engine. It auto-creates historical playlist rows
    from actual family wins and asks: once the member is known, did the straight
    gate candidates include the exact straight?
    """
    family = "".join(sorted(set(str(family).zfill(3))))
    members = [norm_member(m) for m in members if norm_member(m)]
    members = [m for m in members if is_aabc_member(m) and family_from_member(m) == family]
    rows = []
    for m in members:
        ev = build_event_dataset_from_history(hist, m)
        if ev.empty:
            continue
        ev["event_date_dt"] = pd.to_datetime(ev["event_date"], errors="coerce")
        ev = ev[ev["event_date_dt"] > pd.to_datetime(train_cutoff)].copy()
        if test_start is not None:
            ev = ev[ev["event_date_dt"] >= pd.to_datetime(test_start)].copy()
        if test_end is not None:
            ev = ev[ev["event_date_dt"] <= pd.to_datetime(test_end)].copy()
        freq_order = history_frequency_order(hist, m, train_cutoff=train_cutoff)
        for _, r in ev.iterrows():
            seed = str(r["seed"])
            actual = str(r["winning_perm"])
            scored, fired = score_member_seed(m, seed, rules, top_n_gates=max(top_gate_levels) if top_gate_levels else 3)
            rec = {
                "event_date": pd.to_datetime(r["event_date"]).date().isoformat(),
                "stream": r["stream"],
                "family": family,
                "member": m,
                "seed_date": pd.to_datetime(r["seed_date"]).date().isoformat(),
                "seed": seed,
                "actual_straight": actual,
                "available_rule_count_for_member": int((rules["member"] == m).sum()) if not rules.empty else 0,
                "frequency_rank": (freq_order.index(actual) + 1) if actual in freq_order else None,
            }
            for n in top_gate_levels:
                cands = candidates_from_top_gates(scored, n) if scored else freq_order[:min(12, n*3)]
                rec[f"top{n}_gate_candidates"] = "|".join(cands)
                rec[f"top{n}_gate_play_count"] = len(cands)
                rec[f"top{n}_gate_captured"] = int(actual in cands)
            if scored:
                rec["top1_gate"] = scored[0].get("gate", "")
                rec["top1_gate_size"] = scored[0].get("gate_size", "")
                rec["top1_best_rule"] = scored[0].get("best_rule", "")
                rec["top1_score"] = scored[0].get("score", "")
            else:
                rec["top1_gate"] = "NO_RULES_FREQ_FALLBACK"
                rec["top1_gate_size"] = ""
                rec["top1_best_rule"] = "NO_RULES_FREQ_FALLBACK"
                rec["top1_score"] = ""
            rows.append(rec)
    events = pd.DataFrame(rows).sort_values(["event_date", "stream", "member"]).reset_index(drop=True) if rows else pd.DataFrame()
    summary_rows = []
    if not events.empty:
        total_family_events = len(events)
        for n in top_gate_levels:
            summary_rows.append({
                "scope": f"family_{family}_truth_member_future_after_{pd.to_datetime(train_cutoff).date()}",
                "gate_level": f"Top{n} gates",
                "captured_straight_wins": int(events[f"top{n}_gate_captured"].sum()),
                "denominator_family_wins": total_family_events,
                "capture_pct": round(float(events[f"top{n}_gate_captured"].mean()) * 100, 2),
                "total_straight_plays": int(events[f"top{n}_gate_play_count"].sum()),
                "avg_plays_per_family_win": round(float(events[f"top{n}_gate_play_count"].mean()), 3),
                "members_included": ",".join(sorted(events["member"].unique())),
            })
        for m, g in events.groupby("member"):
            for n in top_gate_levels:
                summary_rows.append({
                    "scope": f"member_{m}_truth_member_future_after_{pd.to_datetime(train_cutoff).date()}",
                    "gate_level": f"Top{n} gates",
                    "captured_straight_wins": int(g[f"top{n}_gate_captured"].sum()),
                    "denominator_family_wins": total_family_events,
                    "subset_member_wins": len(g),
                    "capture_pct_within_member": round(float(g[f"top{n}_gate_captured"].mean()) * 100, 2),
                    "capture_pct_of_family_denominator": round(int(g[f"top{n}_gate_captured"].sum()) / max(1, total_family_events) * 100, 2),
                    "total_straight_plays": int(g[f"top{n}_gate_play_count"].sum()),
                    "avg_plays_per_member_win": round(float(g[f"top{n}_gate_play_count"].mean()), 3),
                    "members_included": m,
                })
    return events, pd.DataFrame(summary_rows)


def make_backtest_txt(summary: pd.DataFrame, events: pd.DataFrame, train_cutoff) -> str:
    lines = [f"{BUILD_ID} HISTORICAL TRUTH-MEMBER BACKTEST", "="*78, f"Training cutoff: {pd.to_datetime(train_cutoff).date()}", ""]
    if summary.empty:
        lines.append("No backtest events found.")
        return "\n".join(lines)
    lines.append("SUMMARY")
    lines.append(summary.to_string(index=False))
    lines.append("")
    lines.append("EVENTS")
    show_cols = [c for c in ["event_date","stream","member","seed","actual_straight","top1_gate_candidates","top1_gate_captured","top2_gate_candidates","top2_gate_captured","top3_gate_candidates","top3_gate_captured"] if c in events.columns]
    lines.append(events[show_cols].to_string(index=False))
    return "\n".join(lines)

def make_txt_report(out: pd.DataFrame) -> str:
    lines = [f"{BUILD_ID} STRAIGHT PLAY DECISION OUTPUT", "=" * 72, ""]
    for _, r in out.iterrows():
        lines.append(f"Stream: {r.get('stream','')}")
        lines.append(f"Date: {r.get('play_date','')} | Member: {r.get('member','')} | Seed: {r.get('seed','')}")
        lines.append(f"Top1 Gate: {r.get('top1_gate','')} | Gate Plays: {r.get('top1_candidates','')}")
        lines.append(f"Provisional single straight: {r.get('single_straight_candidate','')}")
        lines.append(f"Reason: {r.get('top1_best_rule','')}")
        lines.append("-" * 72)
    return "\n".join(lines)

# -------------------------
# Streamlit UI
# -------------------------

st.set_page_config(page_title="AABC Straight Play Decision Engine", layout="wide")
st.title("AABC Straight Play Decision Engine")
st.caption(BUILD_ID)

st.markdown(
    "This companion app uses a known boxed member from your final daily playlist and recommends exact straight candidates using the trained adaptive-gate rule database."
)

with st.sidebar:
    st.header("Inputs")
    history_file = st.file_uploader("History file (.csv/.txt/.tsv)", type=["csv", "txt", "tsv"])
    playlist_file = st.file_uploader("Final daily playlist (.csv/.txt/.tsv)", type=["csv", "txt", "tsv"])
    rule_file = st.file_uploader("Optional rule database (.csv/.txt)", type=["csv", "txt", "tsv"])
    train_cutoff = st.date_input("Manual training cutoff for rebuilding rules (optional)", value=None)
    st.caption("Backtest mode is leakage-guarded: it trains a temporary cutoff-safe rule DB automatically, even if a full-history rule DB is uploaded.")

# Load history
hist_norm = pd.DataFrame()
if history_file is not None:
    try:
        hist_raw = read_table_upload(history_file)
        hist_norm = normalize_history(hist_raw)
        st.success(f"Loaded history: {len(hist_norm):,} rows, {hist_norm['date'].min().date()} through {hist_norm['date'].max().date()}.")
    except Exception as e:
        st.error(f"Could not read history: {e}")

# Load rules
rule_db = pd.DataFrame()
if rule_file is not None:
    try:
        rule_db = load_rule_db_from_upload(rule_file)
        st.success(f"Loaded rule database: {len(rule_db):,} rules for {rule_db['member'].nunique()} members.")
    except Exception as e:
        st.error(f"Could not read rule database: {e}")
else:
    p = Path(__file__).with_name(DEFAULT_RULE_DB)
    if p.exists():
        rule_db = normalize_rule_db(pd.read_csv(p, dtype=str))
        st.info(f"Using packaged rule database: {len(rule_db):,} rules for {rule_db['member'].nunique()} members.")
    else:
        local_p = Path(DEFAULT_RULE_DB)
        if local_p.exists():
            rule_db = normalize_rule_db(pd.read_csv(local_p, dtype=str))
            st.info(f"Using local rule database: {len(rule_db):,} rules.")
        else:
            st.warning("No rule database found. Upload one or rebuild from history below.")

st.subheader("Rule database builder / updater")
with st.expander("Build or update member rule database", expanded=False):
    st.write("Use this to add new AABC members as we expand to more cores. Enter members as 4 digits, comma-separated.")
    members_text = st.text_input("Members to train", value="0025,0225,0255")
    max_gate_size = st.slider("Max gate size", min_value=1, max_value=3, value=3)
    min_rule_pos = st.slider("Minimum target support per rule", min_value=1, max_value=5, value=2)
    if st.button("Train/update rule database from uploaded history", type="primary"):
        if hist_norm.empty:
            st.error("Upload a history file first.")
        else:
            members = []
            for part in re.split(r"[,;\s]+", members_text.strip()):
                if not part:
                    continue
                m = norm_member(part)
                if m and is_aabc_member(m):
                    members.append(m)
            if not members:
                st.error("No valid AABC members found.")
            else:
                dfs = []
                prog = st.progress(0)
                for idx, m in enumerate(members):
                    st.write(f"Training {m}...")
                    ev = build_event_dataset_from_history(hist_norm, m)
                    cutoff_ts = pd.to_datetime(train_cutoff) if train_cutoff else None
                    lib = train_adaptive_gate_rules(ev, m, cutoff_ts, max_gate_size=max_gate_size, min_rule_pos=min_rule_pos)
                    if not lib.empty:
                        dfs.append(lib)
                    prog.progress((idx + 1) / len(members))
                new_db = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
                if not rule_db.empty:
                    combined = pd.concat([rule_db, new_db], ignore_index=True)
                    # Dedupe exact same member/gate/atoms/cutoff.
                    combined = combined.drop_duplicates(subset=["member", "gate", "atoms_str", "train_cutoff"], keep="last")
                else:
                    combined = new_db
                st.session_state["trained_rule_db"] = combined
                st.success(f"Updated rule database: {len(combined):,} rules.")

if "trained_rule_db" in st.session_state:
    rule_db = normalize_rule_db(st.session_state["trained_rule_db"])

if not rule_db.empty:
    csv_bytes = rule_db.to_csv(index=False).encode("utf-8")
    txt_bytes = rule_db.to_csv(index=False, sep="\t").encode("utf-8")
    c1, c2 = st.columns(2)
    c1.download_button("Download rule DB CSV", csv_bytes, file_name="straight_rule_database_updated.csv", mime="text/csv")
    c2.download_button("Download rule DB TXT", txt_bytes, file_name="straight_rule_database_updated.txt", mime="text/plain")

st.subheader("Straight-play decision output")
if playlist_file is None:
    st.info("Upload the final daily playlist to generate straight recommendations.")
else:
    try:
        playlist_raw = read_table_upload(playlist_file)
        playlist = normalize_playlist(playlist_raw)
        st.write("Playlist preview")
        st.dataframe(playlist.head(25), use_container_width=True)

        auto_member = detect_column(playlist, ["chosen_member", "selected_member", "member", "top1member", "top_member", "finalmember", "recommendmember", "box_member"])
        auto_seed = detect_column(playlist, ["seed", "last_seed", "prior_result", "previous_result", "seed_result"])
        auto_stream = detect_column(playlist, ["stream", "streamkey", "stream_key", "StreamKey"])
        auto_date = detect_column(playlist, ["play_date", "date", "prediction_date", "target_date"])

        c1, c2, c3, c4 = st.columns(4)
        member_col = c1.selectbox("Member column", options=list(playlist.columns), index=list(playlist.columns).index(auto_member) if auto_member in playlist.columns else 0)
        seed_options = ["<derive from history>"] + list(playlist.columns)
        seed_col = c2.selectbox("Seed column", options=seed_options, index=(seed_options.index(auto_seed) if auto_seed in seed_options else 0))
        stream_options = ["<none>"] + list(playlist.columns)
        stream_col = c3.selectbox("Stream column", options=stream_options, index=(stream_options.index(auto_stream) if auto_stream in stream_options else 0))
        date_options = ["<none>"] + list(playlist.columns)
        date_col = c4.selectbox("Play date column", options=date_options, index=(date_options.index(auto_date) if auto_date in date_options else 0))

        top_n_gates = st.slider("How many gates to display", min_value=1, max_value=6, value=3)
        output_rows = []
        fired_all = []
        for idx, row in playlist.iterrows():
            member = norm_member(row.get(member_col))
            if not member or not is_aabc_member(member):
                continue
            play_date = None
            if date_col != "<none>":
                play_date = pd.to_datetime(row.get(date_col), errors="coerce")
            stream = str(row.get(stream_col, "")) if stream_col != "<none>" else ""
            if seed_col != "<derive from history>":
                seed = norm4(row.get(seed_col))
            else:
                seed = find_seed_from_history(hist_norm, stream, play_date) if not hist_norm.empty else None
            if not seed:
                output_rows.append({
                    "playlist_row": idx,
                    "stream": stream,
                    "play_date": str(play_date.date()) if play_date is not None and not pd.isna(play_date) else "",
                    "member": member,
                    "seed": "MISSING",
                    "status": "NO SEED AVAILABLE",
                })
                continue
            scored, fired = score_member_seed(member, seed, rule_db, top_n_gates=max(6, top_n_gates)) if not rule_db.empty else ([], pd.DataFrame())
            if not scored:
                scored = []
            # Frequency fallback order for provisional single ranking.
            freq_order = history_frequency_order(hist_norm, member) if not hist_norm.empty else unique_perms(member)
            top1_cands = candidates_from_top_gates(scored, 1) if scored else freq_order[:3]
            top2_cands = candidates_from_top_gates(scored, 2) if scored else freq_order[:6]
            top3_cands = candidates_from_top_gates(scored, 3) if scored else freq_order[:9]
            # Provisional single straight: highest frequency among Top1 gate candidates.
            single = sorted(top1_cands, key=lambda p: (freq_order.index(p) if p in freq_order else 999, p))[0] if top1_cands else ""
            rec = {
                "playlist_row": idx,
                "stream": stream,
                "play_date": str(play_date.date()) if play_date is not None and not pd.isna(play_date) else "",
                "member": member,
                "family": family_from_member(member),
                "seed": seed,
                "status": "OK" if not rule_db.empty else "NO RULE DB - FREQ FALLBACK",
                "top1_gate": scored[0]["gate"] if scored else "FREQ_FALLBACK",
                "top1_gate_size": len(top1_cands),
                "top1_candidates": "|".join(top1_cands),
                "top2_gate_candidates": "|".join(top2_cands),
                "top3_gate_candidates": "|".join(top3_cands),
                "single_straight_candidate": single,
                "top1_best_rule": scored[0]["best_rule"] if scored else "FREQ_FALLBACK",
                "top1_rule_count": scored[0]["rule_count"] if scored else 0,
                "top1_score": round(scored[0]["score"], 4) if scored else 0,
            }
            output_rows.append(rec)
            if fired is not None and not fired.empty:
                tmp = fired.copy()
                tmp = safe_front_col(tmp, 0, "playlist_row", idx)
                tmp = safe_front_col(tmp, 1, "member", member)
                tmp = safe_front_col(tmp, 2, "seed", seed)
                fired_all.append(tmp)
        out = pd.DataFrame(output_rows)
        st.write("Straight recommendations")
        st.dataframe(out, use_container_width=True)
        if not out.empty:
            csv = out.to_csv(index=False).encode("utf-8")
            txt = make_txt_report(out).encode("utf-8")
            c1, c2 = st.columns(2)
            c1.download_button("Download straight recommendations CSV", csv, file_name="straight_play_recommendations.csv", mime="text/csv")
            c2.download_button("Download straight recommendations TXT", txt, file_name="straight_play_recommendations.txt", mime="text/plain")
        if fired_all:
            fired_df = pd.concat(fired_all, ignore_index=True)
            st.write("Fired rule detail")
            st.dataframe(fired_df.head(500), use_container_width=True)
            st.download_button("Download fired rule detail CSV", fired_df.to_csv(index=False).encode("utf-8"), file_name="straight_fired_rule_detail.csv", mime="text/csv")
    except Exception as e:
        st.error(f"Could not process playlist: {e}")



# -------------------------
# Seed + Member operational audit helpers
# -------------------------

def build_seed_member_audit_list_from_history(hist: pd.DataFrame, members: Sequence[str]) -> pd.DataFrame:
    """Build a no-playlist audit list from history.

    This does NOT use the actual straight as an input. It derives only:
      event_date, stream, seed/prior-result, and base member.
    The actual result is intentionally omitted from the default audit input so the
    recommendation path mirrors live use: Seed + chosen Member -> straight candidates.
    """
    if hist is None or hist.empty:
        return pd.DataFrame()
    mems = [norm_member(m) for m in members if norm_member(m)]
    mems = [m for m in mems if is_aabc_member(m)]
    if not mems:
        return pd.DataFrame()
    df = hist.copy()
    if "date" not in df.columns or "result4" not in df.columns or "stream" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["result4"] = df["result4"].map(norm4)
    df = df.dropna(subset=["date", "result4", "stream"]).sort_values(["stream", "date"]).copy()
    df["seed"] = df.groupby("stream")["result4"].shift(1)
    df["member"] = df["result4"].map(norm_member)
    ev = df[df["member"].isin(mems)].copy()
    ev = ev[ev["seed"].map(lambda x: norm4(x) is not None)].copy()
    if ev.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "event_date": ev["date"].dt.strftime("%Y-%m-%d"),
        "stream": ev["stream"].astype(str),
        "seed": ev["seed"].map(norm4),
        "member": ev["member"].astype(str),
        "family": ev["member"].astype(str).map(family_from_member),
    })
    out.insert(0, "audit_id", range(1, len(out) + 1))
    return out.reset_index(drop=True)


def normalize_seed_member_audit_input(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize manual audit file to seed/member rows.
    Required: seed + member. Optional: stream, event_date/date.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data.columns = [str(c).strip() for c in data.columns]
    seed_col = detect_column(data, ["seed", "prior_result", "previous_result", "last_seed", "seed_result"])
    member_col = detect_column(data, ["member", "base_member", "chosen_member", "selected_member", "box_member"])
    stream_col = detect_column(data, ["stream", "streamkey", "stream_key", "StreamKey"])
    date_col = detect_column(data, ["event_date", "play_date", "date", "prediction_date", "target_date"])
    if not seed_col or not member_col:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["audit_id"] = range(1, len(data) + 1)
    out["event_date"] = data[date_col].astype(str) if date_col else ""
    out["stream"] = data[stream_col].astype(str) if stream_col else ""
    out["seed"] = data[seed_col].map(norm4)
    out["member"] = data[member_col].map(norm_member)
    out = out[out["seed"].notna() & out["member"].notna()].copy()
    out = out[out["member"].map(is_aabc_member)].copy()
    out["family"] = out["member"].map(family_from_member)
    return out.reset_index(drop=True)


def run_seed_member_operational_audit(audit_df: pd.DataFrame, rules: pd.DataFrame, hist: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run current rule database against Seed + Member only.

    This is an operational audit, not a blind validation: it proves the money-facing
    decision path can route rows, fire rules, and produce candidate straights.
    """
    rows = []
    fired_parts = []
    if audit_df is None or audit_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    for _, row in audit_df.iterrows():
        seed = norm4(row.get("seed"))
        member = norm_member(row.get("member"))
        base = {
            "audit_id": row.get("audit_id", ""),
            "event_date": row.get("event_date", ""),
            "stream": row.get("stream", ""),
            "member": member or "",
            "family": family_from_member(member) if member else "",
            "seed": seed or "",
        }
        if not seed or not member or not is_aabc_member(member):
            rows.append({**base, "status": "BAD_SEED_OR_MEMBER"})
            continue
        if rules is None or rules.empty:
            freq_order = history_frequency_order(hist, member) if hist is not None and not hist.empty else unique_perms(member)
            top1_cands = freq_order[:3]
            top2_cands = freq_order[:6]
            top3_cands = freq_order[:9]
            single = top1_cands[0] if top1_cands else ""
            rows.append({
                **base,
                "status": "NO_RULE_DB_FREQ_FALLBACK",
                "top1_gate": "FREQ_FALLBACK",
                "top1_gate_size": len(top1_cands),
                "top1_candidates": "|".join(top1_cands),
                "top2_gate_candidates": "|".join(top2_cands),
                "top3_gate_candidates": "|".join(top3_cands),
                "single_straight_candidate": single,
                "top1_best_rule": "FREQ_FALLBACK",
                "top1_rule_count": 0,
                "top1_score": 0,
                "fired_rule_count": 0,
            })
            continue
        scored, fired = score_member_seed(member, seed, rules, top_n_gates=6)
        freq_order = history_frequency_order(hist, member) if hist is not None and not hist.empty else unique_perms(member)
        top1_cands = candidates_from_top_gates(scored, 1) if scored else freq_order[:3]
        top2_cands = candidates_from_top_gates(scored, 2) if scored else freq_order[:6]
        top3_cands = candidates_from_top_gates(scored, 3) if scored else freq_order[:9]
        single = sorted(top1_cands, key=lambda p: (freq_order.index(p) if p in freq_order else 999, p))[0] if top1_cands else ""
        status = "OK_RULES_FIRED" if fired is not None and not fired.empty else "NO_RULE_FIRED_FREQ_FALLBACK"
        rows.append({
            **base,
            "status": status,
            "top1_gate": scored[0]["gate"] if scored else "FREQ_FALLBACK",
            "top1_gate_size": len(top1_cands),
            "top1_candidates": "|".join(top1_cands),
            "top2_gate_candidates": "|".join(top2_cands),
            "top3_gate_candidates": "|".join(top3_cands),
            "single_straight_candidate": single,
            "top1_best_rule": scored[0]["best_rule"] if scored else "FREQ_FALLBACK",
            "top1_rule_count": scored[0]["rule_count"] if scored else 0,
            "top1_score": round(scored[0]["score"], 4) if scored else 0,
            "fired_rule_count": 0 if fired is None or fired.empty else len(fired),
        })
        if fired is not None and not fired.empty:
            tmp = fired.copy()
            tmp = safe_front_col(tmp, 0, "audit_id", row.get("audit_id", ""))
            tmp = safe_front_col(tmp, 1, "member", member)
            tmp = safe_front_col(tmp, 2, "seed", seed)
            tmp = safe_front_col(tmp, 3, "stream", row.get("stream", ""))
            tmp = safe_front_col(tmp, 4, "event_date", row.get("event_date", ""))
            fired_parts.append(tmp)
    result = pd.DataFrame(rows)
    fired_detail = pd.concat(fired_parts, ignore_index=True) if fired_parts else pd.DataFrame()
    if result.empty:
        summary = pd.DataFrame()
    else:
        summary = pd.DataFrame([
            {"metric": "rows_processed", "value": len(result)},
            {"metric": "rows_ok_rules_fired", "value": int((result["status"] == "OK_RULES_FIRED").sum())},
            {"metric": "rows_no_rule_fired_freq_fallback", "value": int((result["status"] == "NO_RULE_FIRED_FREQ_FALLBACK").sum())},
            {"metric": "rows_bad_seed_or_member", "value": int((result["status"] == "BAD_SEED_OR_MEMBER").sum())},
            {"metric": "unique_members", "value": int(result["member"].nunique())},
            {"metric": "unique_top1_gates", "value": int(result["top1_gate"].nunique()) if "top1_gate" in result.columns else 0},
            {"metric": "avg_top1_gate_size", "value": round(float(pd.to_numeric(result.get("top1_gate_size", 0), errors="coerce").fillna(0).mean()), 3)},
        ])
    return result, fired_detail, summary


def make_audit_txt_report(result: pd.DataFrame, summary: pd.DataFrame) -> str:
    lines = [f"{BUILD_ID} SEED+MEMBER OPERATIONAL AUDIT", "=" * 78, ""]
    lines.append("This is NOT blind edge proof. It is a current-rule operational replay audit.")
    lines.append("Input required only Seed + Member; actual straight is not used.")
    lines.append("")
    if summary is not None and not summary.empty:
        lines.append("SUMMARY")
        for _, r in summary.iterrows():
            lines.append(f"{r.get('metric')}: {r.get('value')}")
        lines.append("")
    lines.append("EVENTS")
    if result is None or result.empty:
        lines.append("No audit rows.")
    else:
        for _, r in result.iterrows():
            lines.append(f"{str(r.get('audit_id','')).zfill(3)} | {r.get('event_date','')} | {r.get('stream','')} | seed={r.get('seed','')} member={r.get('member','')} status={r.get('status','')}")
            lines.append(f"   Top1: {r.get('top1_candidates','')} | Single: {r.get('single_straight_candidate','')}")
            lines.append(f"   Rule: {r.get('top1_best_rule','')}")
    return "\n".join(lines)


st.subheader("Seed + Member operational audit — no playlist required")
st.caption("This is a current-rule functionality audit, not blind edge proof. It uses only Seed + Member to confirm routing, gate selection, fired rules, and candidate generation.")
with st.expander("Run Seed + Member audit", expanded=False):
    audit_upload = st.file_uploader("Optional audit input with Seed + Member (.csv/.txt/.tsv)", type=["csv", "txt", "tsv"], key="seed_member_audit_upload")
    ac1, ac2, ac3 = st.columns(3)
    audit_members_text = ac1.text_input("Members for history-generated audit list", value="0025,0225,0255", key="audit_members_text")
    audit_row_cap = ac2.number_input("Optional row cap; 0 = all", min_value=0, max_value=1000000, value=0, step=100, key="audit_row_cap")
    audit_source = ac3.radio("Audit source", ["Generate from uploaded history", "Use uploaded Seed+Member file"], index=0, key="audit_source")

    st.write("Expected manual input columns: `seed` and `member`. Optional: `event_date`, `stream`.")
    if st.button("Run Seed + Member operational audit", type="primary", key="run_seed_member_audit"):
        try:
            if audit_source == "Use uploaded Seed+Member file":
                if audit_upload is None:
                    st.error("Upload a Seed + Member audit file first.")
                    audit_df = pd.DataFrame()
                else:
                    audit_df = normalize_seed_member_audit_input(read_table_upload(audit_upload))
            else:
                mems = [norm_member(x) for x in re.split(r"[,;\s]+", audit_members_text) if norm_member(x)]
                if hist_norm.empty:
                    st.error("Upload a history file first.")
                    audit_df = pd.DataFrame()
                else:
                    audit_df = build_seed_member_audit_list_from_history(hist_norm, mems)
            if audit_row_cap and audit_row_cap > 0 and audit_df is not None and not audit_df.empty:
                audit_df = audit_df.head(int(audit_row_cap)).copy()
            if audit_df is None or audit_df.empty:
                st.warning("No audit rows available. Check history/audit input and selected members.")
            else:
                with st.spinner("Running Seed + Member audit through current rule path..."):
                    audit_result, audit_fired, audit_summary = run_seed_member_operational_audit(audit_df, rule_db, hist_norm)
                st.session_state["seed_member_audit_input"] = audit_df
                st.session_state["seed_member_audit_result"] = audit_result
                st.session_state["seed_member_audit_fired"] = audit_fired
                st.session_state["seed_member_audit_summary"] = audit_summary
                st.success(f"Audit complete: {len(audit_result):,} rows processed.")
        except Exception as e:
            st.error(f"Seed + Member audit failed: {e}")

if "seed_member_audit_result" in st.session_state:
    audit_result = st.session_state["seed_member_audit_result"]
    audit_fired = st.session_state.get("seed_member_audit_fired", pd.DataFrame())
    audit_summary = st.session_state.get("seed_member_audit_summary", pd.DataFrame())
    audit_input = st.session_state.get("seed_member_audit_input", pd.DataFrame())
    st.write("Seed + Member audit summary")
    st.dataframe(audit_summary, use_container_width=True)
    st.write("Seed + Member audit recommendations")
    st.dataframe(audit_result.head(1000), use_container_width=True)
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Download audit input CSV", audit_input.to_csv(index=False).encode("utf-8"), file_name="seed_member_audit_input.csv", mime="text/csv")
    d2.download_button("Download audit result CSV", audit_result.to_csv(index=False).encode("utf-8"), file_name="seed_member_operational_audit_results.csv", mime="text/csv")
    d3.download_button("Download audit TXT", make_audit_txt_report(audit_result, audit_summary).encode("utf-8"), file_name="seed_member_operational_audit_report.txt", mime="text/plain")
    if audit_fired is not None and not audit_fired.empty:
        d4.download_button("Download fired-rule detail CSV", audit_fired.to_csv(index=False).encode("utf-8"), file_name="seed_member_audit_fired_rule_detail.csv", mime="text/csv")
        with st.expander("Fired rule detail preview", expanded=False):
            st.dataframe(audit_fired.head(500), use_container_width=True)


st.subheader("Historical backtest mode — no winning playlist required")
st.caption("Leakage guard: backtest ignores any uploaded/full-history rule database and trains a temporary cutoff-safe rule DB from history through the selected train-through date.")
with st.expander("Run truth-member historical backtest", expanded=False):
    if hist_norm.empty:
        st.info("Upload a history file first.")
    else:
        bc1, bc2, bc3 = st.columns(3)
        bt_family = bc1.text_input("Core family", value="025")
        bt_members = bc2.text_input("Members to include", value="0025,0225,0255")
        min_d = hist_norm["date"].min().date()
        max_d = hist_norm["date"].max().date()
        auto_cutoff = infer_default_train_cutoff(hist_norm).date()
        auto_cutoff = min(max(auto_cutoff, min_d), max_d)
        bt_cutoff = bc3.date_input("Train through date", value=auto_cutoff, min_value=min_d, max_value=max_d)
        bc4, bc5, bc6 = st.columns(3)
        bt_start = bc4.date_input("Optional test start", value=(pd.to_datetime(bt_cutoff) + pd.Timedelta(days=1)).date(), min_value=min_d, max_value=max_d)
        bt_end = bc5.date_input("Optional test end", value=max_d, min_value=min_d, max_value=max_d)
        bt_max_gate_size = bc6.slider("Max gate size", min_value=1, max_value=3, value=3, key="bt_max_gate_size")
        st.caption("Default cutoff uses 2026-02-20 when that date exists in the history; otherwise it uses an 80% chronological split. Events must be after the train-through date.")
        if st.button("Run leakage-safe historical backtest", type="primary"):
            mems = [norm_member(x) for x in re.split(r"[,;\s]+", bt_members) if norm_member(x)]
            mems = [m for m in mems if is_aabc_member(m)]
            with st.spinner("Training temporary cutoff-safe rules and running backtest..."):
                temp_rules = train_cutoff_safe_rules_for_members(hist_norm, mems, pd.to_datetime(bt_cutoff), max_gate_size=bt_max_gate_size, min_rule_pos=2)
                events, summ = backtest_truth_member(
                    hist_norm,
                    temp_rules,
                    family=bt_family,
                    members=mems,
                    train_cutoff=pd.to_datetime(bt_cutoff),
                    test_start=pd.to_datetime(bt_start) if bt_start else None,
                    test_end=pd.to_datetime(bt_end) if bt_end else None,
                    top_gate_levels=(1,2,3),
                )
            st.session_state["backtest_events"] = events
            st.session_state["backtest_summary"] = summ
            st.session_state["backtest_cutoff"] = pd.to_datetime(bt_cutoff)
            st.session_state["backtest_temp_rules"] = temp_rules
            st.success(f"Backtest used {len(temp_rules):,} temporary cutoff-safe rules trained through {pd.to_datetime(bt_cutoff).date()}.")

if "backtest_summary" in st.session_state:
    st.write("Backtest summary")
    st.dataframe(st.session_state["backtest_summary"], use_container_width=True)
    st.write("Backtest events")
    st.dataframe(st.session_state["backtest_events"], use_container_width=True)
    bt_summary = st.session_state["backtest_summary"]
    bt_events = st.session_state["backtest_events"]
    bt_rules = st.session_state.get("backtest_temp_rules", pd.DataFrame())
    bt_txt = make_backtest_txt(bt_summary, bt_events, st.session_state.get("backtest_cutoff", pd.Timestamp("today"))).encode("utf-8")
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.download_button("Download backtest summary CSV", bt_summary.to_csv(index=False).encode("utf-8"), file_name="straight_backtest_summary.csv", mime="text/csv")
    bc2.download_button("Download backtest events CSV", bt_events.to_csv(index=False).encode("utf-8"), file_name="straight_backtest_events.csv", mime="text/csv")
    bc3.download_button("Download backtest TXT", bt_txt, file_name="straight_backtest_report.txt", mime="text/plain")
    if bt_rules is not None and not bt_rules.empty:
        bc4.download_button("Download cutoff-safe rules CSV", bt_rules.to_csv(index=False).encode("utf-8"), file_name="straight_backtest_cutoff_safe_rules.csv", mime="text/csv")

st.divider()
st.caption("Scope note: current packaged rules cover CORE025 members 0025, 0225, and 0255. Use the trainer to add future members as we build them.")
