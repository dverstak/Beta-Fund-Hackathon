"""CLI entrypoint for the Independent Contractor Tax & Deduction Auditor.

Usage:
    python -m auditor.cli audit <input_path> [--out OUT_DIR] [--quiet]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="auditor",
        description="Autonomous Independent Contractor Tax & Deduction Auditor "
                    "(Schedule C). Powered by GMI Cloud + Respan.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="audit a folder of documents")
    a.add_argument("input", help="file or folder of spreadsheets/receipts/1099s")
    a.add_argument("--out", default="audit_out", help="output directory")
    a.add_argument("--quiet", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "audit":
        result = run(Path(args.input), Path(args.out), verbose=not args.quiet)
        s = result["ledger"]["summary"]
        r = result["respan"]
        print("\n=== AUDIT COMPLETE ===")
        print(f"Gross receipts:      ${s['gross_receipts']:,.2f}")
        print(f"Total deductible:    ${s['total_deductible']:,.2f}")
        print(f"Est. net profit:     ${s['estimated_net_profit_schedule_c']:,.2f}")
        print(f"Flagged / high-risk: {s['flagged_items']} / {s['high_risk_items']}")
        tel = r["respan_telemetry"]
        print(f"[respan] {r['calls']} calls, {r['total_tokens']} tokens, "
              f"${r['total_cost_usd']:.4f} "
              f"(~${r['avg_cost_per_call_usd']:.4f}/doc) | "
              f"telemetry {'ON' if tel['enabled'] else 'off'} "
              f"({tel['logs_sent']} logs sent, {tel['log_errors']} errors)")
        print(f"Reports: {result['paths']['audit_report_md']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
