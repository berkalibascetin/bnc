"""python -m score_scan  →  patched freqtrade CLI with --score-scan."""

from score_scan.cli_patch import main

if __name__ == "__main__":
    raise SystemExit(main())
