import os
import sys

os.environ.setdefault("GDK_BACKEND", "x11")

from .ui import run


if __name__ == "__main__":
    sys.exit(run())
