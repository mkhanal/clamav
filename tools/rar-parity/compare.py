#!/usr/bin/env python3
"""Scan the RAR parity fixtures with two ClamAV builds and compare the verdicts.

  compare.py --a docker:clamav-rar-unrar --b docker:clamav-rar-libarchive
  compare.py --a prefix:/opt/clamav-unrar --b prefix:/opt/clamav-libarchive
  compare.py --a docker:clamav-rar-unrar --report-only      # baseline, manifest only

A is the reference build (unRAR), B the build under test (libarchive backend).
Exit status is non-zero when, for any row, B
  - detects less than A (a detection in A that B lacks),
  - reports clean where A alerted or errored, or
  - differs from the manifest's expected outcome.
With --report-only the table is printed and the exit status is 0 unless a build
cannot be run; use it to record a baseline.

Expected outcomes (manifest.json, field expected.kind):
  detect     every signature in expected.detect fires: the inner content was extracted
  encrypted  Heuristics.Encrypted.RAR (run with --alert-encrypted-archive)
  limits     Heuristics.Limits.Exceeded (run with --alert-exceeds-max)
  error      anything but a clean verdict: an alert or a scan error
  clean      archive holds nothing scannable; no RarParity detection expected
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rarwrite  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ENCRYPTED = "Heuristics.Encrypted.RAR"
LIMITS = "Heuristics.Limits.Exceeded"
XOR_KEY = b"bhcftqarohcdiayfohalohkgmoefxrrgfnczssgybajvkzjaahpfrlqsratkhhfvpxytculmwgmtyzujlbjlgrhtwxhzpjazlibbwepffyjyfkjwzyofgpopoueurinpdujkphxwhnaxfkaiwrpzdqsnwughtejr"
BASE_OPTIONS = ["-z", "--alert-encrypted-archive=yes", "--alert-exceeds-max=yes", "--no-summary"]


def runtime_large_stored(v: int):
    def make(path: str) -> None:
        w = rarwrite.rar4_archive if v == 4 else rarwrite.rar5_archive
        with open(path, "wb") as f:
            f.write(w([("big.bin", b"\0" * (110 * 1024 * 1024))]))
    return make


def runtime_many_files(v: int):
    def make(path: str) -> None:
        w = rarwrite.rar4_archive if v == 4 else rarwrite.rar5_archive
        with open(path, "wb") as f:
            f.write(w([(f"f{i:05d}", f"{i:08d}".encode()) for i in range(10100)]))
    return make


RUNTIME = {
    "large-entry-stored-rar4": runtime_large_stored(4),
    "large-entry-stored-rar5": runtime_large_stored(5),
    "many-files-stored-rar4": runtime_many_files(4),
    "many-files-stored-rar5": runtime_many_files(5),
}


def stage(rows: list[dict], work: str) -> None:
    for r in rows:
        dst = os.path.join(work, r["staged"])
        if "runtime" in r:
            RUNTIME[r["runtime"]](dst)
            continue
        src = os.path.join(REPO, r["file"]) if r["source"] == "clamav" else os.path.join(HERE, "fixtures", r["file"])
        with open(src, "rb") as f:
            data = f.read()
        if r["source"] == "clamav":
            data = bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data))
        with open(dst, "wb") as f:
            f.write(data)


def runner_script(rows: list[dict]) -> str:
    lines = ["cd /fx"]
    for r in rows:
        cmd = ["clamscan", "-d", "/sigs"] + BASE_OPTIONS + r.get("options", []) + [r["staged"]]
        lines.append(f"echo '@@ROW {r['staged']}'")
        lines.append(f"timeout 300 {' '.join(shlex.quote(c) for c in cmd)} 2>/tmp/rp.err; echo \"@@RC $?\"; echo '@@ERR'; cat /tmp/rp.err")
    return "\n".join(lines)


def run_build(spec: str, rows: list[dict], work: str) -> dict[str, dict]:
    kind, _, target = spec.partition(":")
    script = runner_script(rows)
    sigs = os.path.join(HERE, "signatures")
    if kind == "docker":
        cmd = ["docker", "run", "--rm", "-v", f"{work}:/fx:ro", "-v", f"{sigs}:/sigs:ro", target, "sh", "-c", script]
        env = None
    elif kind == "prefix":
        prefix = os.path.abspath(target)
        script = script.replace("cd /fx", f"cd {shlex.quote(work)}").replace("-d /sigs", f"-d {shlex.quote(sigs)}")
        cmd = ["sh", "-c", script]
        env = dict(os.environ, PATH=f"{prefix}/bin:{os.environ['PATH']}", LD_LIBRARY_PATH=f"{prefix}/lib", DYLD_LIBRARY_PATH=f"{prefix}/lib")
    else:
        sys.exit(f"build spec must be docker:IMAGE or prefix:PATH, got {spec!r}")
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, errors="replace")
    results: dict[str, dict] = {}
    cur = None
    mode = "out"
    for line in out.stdout.splitlines():
        if line.startswith("@@ROW "):
            cur = line[6:]
            results[cur] = {"found": set(), "rc": None, "err": []}
            mode = "out"
        elif cur is None:
            continue
        elif line.startswith("@@RC "):
            results[cur]["rc"] = int(line[5:])
        elif line == "@@ERR":
            mode = "err"
        elif mode == "out":
            m = re.match(r"^.*: (\S+) FOUND$", line)
            if m:
                results[cur]["found"].add(m.group(1).removesuffix(".UNOFFICIAL"))
        else:
            results[cur]["err"].append(line)
    if len(results) != len(rows):
        sys.exit(f"{spec}: ran {len(results)} of {len(rows)} rows\n{out.stderr[-2000:]}")
    return results


def verdict(res: dict) -> str:
    if res["found"]:
        return "alert"
    if res["rc"] not in (0, 1) or any("error" in l.lower() for l in res["err"]):
        return "error"
    return "clean"


def meets(row: dict, res: dict) -> str | None:
    exp = row["expected"]
    k = exp["kind"]
    found = res["found"]
    if k == "detect":
        missing = [n for n in exp["detect"] if n not in found]
        return f"missing {len(missing)} of {len(exp['detect'])} signatures" if missing else None
    if k == "encrypted":
        return None if ENCRYPTED in found else f"no {ENCRYPTED}"
    if k == "limits":
        return None if any(n.startswith(LIMITS) for n in found) else f"no {LIMITS}*"
    if k == "error":
        return None if verdict(res) != "clean" else "clean verdict, contents not scanned"
    if k == "clean":
        return "unexpected detection" if any(n.startswith("RarParity.") for n in found) else None
    return f"unknown expectation {k}"


def build_rows(manifest: dict, only: str | None, runtime: bool) -> list[dict]:
    rows = []
    for i, r in enumerate(manifest["rows"]):
        if "runtime" in r and not runtime:
            continue
        if only and not re.search(only, r["id"]):
            continue
        rows.append(dict(r, staged=f"r{i:04d}.rar"))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="reference build (unRAR): docker:IMAGE or prefix:PATH")
    ap.add_argument("--b", help="build under test (libarchive): docker:IMAGE or prefix:PATH")
    ap.add_argument("--manifest", default=os.path.join(HERE, "manifest.json"))
    ap.add_argument("--only", help="regex over row ids")
    ap.add_argument("--no-runtime", action="store_true", help="skip the large archives generated at scan time")
    ap.add_argument("--report-only", action="store_true", help="print the table, exit 0 (baseline recording)")
    ap.add_argument("--json", help="write per-row results here")
    args = ap.parse_args()

    with open(args.manifest) as f:
        manifest = json.load(f)
    rows = build_rows(manifest, args.only, not args.no_runtime)
    work = tempfile.mkdtemp(prefix="rarparity-fx-")
    try:
        stage(rows, work)
        ra = run_build(args.a, rows, work)
        rb = run_build(args.b, rows, work) if args.b else None
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failures = 0
    table = []
    for r in rows:
        a = ra[r["staged"]]
        b = rb[r["staged"]] if rb else None
        problems = []
        for label, x in (("A", a), ("B", b)):
            if x is None:
                continue
            why = meets(r, x)
            if why:
                problems.append(f"{label} vs manifest: {why}")
        if b is not None:
            lost = sorted(a["found"] - b["found"])
            if lost:
                problems.append(f"B detects less than A: {', '.join(lost[:3])}{' ...' if len(lost) > 3 else ''}")
            if verdict(a) != "clean" and verdict(b) == "clean":
                problems.append("B clean where A alerted or errored")
        status = "ok" if not problems else "FAIL"
        if problems and not args.report_only:
            failures += 1
        table.append((r["id"], r["category"], r["expected"]["kind"], verdict(a), len(a["found"]), verdict(b) if b else "-", len(b["found"]) if b else 0, status, "; ".join(problems)))
    w = max(len(t[0]) for t in table)
    print(f"{'row':<{w}}  {'category':<10} {'expect':<9} {'A':<6} {'#A':>3}  {'B':<6} {'#B':>3}  status")
    for t in table:
        print(f"{t[0]:<{w}}  {t[1]:<10} {t[2]:<9} {t[3]:<6} {t[4]:>3}  {t[5]:<6} {t[6]:>3}  {t[7]}" + (f"  <- {t[8]}" if t[8] else ""))
    n_ok = sum(1 for t in table if t[7] == "ok")
    print(f"\n{len(table)} rows, {n_ok} ok, {len(table) - n_ok} with problems" + (" (report only)" if args.report_only else ""))
    if args.json:
        with open(args.json, "w") as f:
            json.dump([{"row": t[0], "category": t[1], "expected": t[2], "A": t[3], "B": t[5], "status": t[7], "problems": t[8]} for t in table], f, indent=1)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
