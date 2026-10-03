"""Entry point for ``python -m gchat_cli`` and the ``gchat`` console script."""

from __future__ import annotations

import sys

from gchat_cli.cli import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
