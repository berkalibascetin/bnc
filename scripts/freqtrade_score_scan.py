#!/usr/bin/env python3
"""Drop-in wrapper: same as ``freqtrade`` but registers ``--score-scan``."""

from score_scan.cli_patch import main

if __name__ == "__main__":
    raise SystemExit(main())
