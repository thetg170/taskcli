from __future__ import annotations

from beca_work.config import load_env
from beca_work.runner import run


def main() -> None:
    load_env()
    run()


if __name__ == "__main__":
    main()
