"""Allows `python3 -m drawlogic ...` with nothing installed."""

import sys

from .cli import main

if __name__ == "__main__":
  sys.exit(main())
