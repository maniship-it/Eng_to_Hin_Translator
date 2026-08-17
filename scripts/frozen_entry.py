"""Entry point for the frozen Windows build.

PyInstaller runs its entry script as a top-level module named ``__main__``,
which leaves it with no parent package — so ``anuvad/__main__.py`` cannot be
used directly: its relative imports have nothing to be relative to. This
module imports the package properly and hands over.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # CTranslate2 may spawn workers; without this a frozen build can relaunch
    # the whole application instead of starting a worker process.
    multiprocessing.freeze_support()

    from anuvad.__main__ import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
