"""Run the duplicate-finder CLI via ``python -m duplicate_finder``."""

from .dupes import main

if __name__ == "__main__":
    raise SystemExit(main())
