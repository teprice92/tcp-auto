"""Entry point for the packaged FlagPole app (see flagpole.spec)."""

import multiprocessing
import sys

from tcp_auto.launcher import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
