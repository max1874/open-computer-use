#!/usr/bin/env python3
"""Calculator uses the shared full-lifetime acceptance runner and owned instance.

Supply --max-calls, --usage-file and --output for your approved model-call batch.
Optional --goal and --expect keep the single-task example configurable.
"""
import sys

from evals.run import main

if __name__ == "__main__":
    main(["--tasks", "calc-multiply", *sys.argv[1:]])
