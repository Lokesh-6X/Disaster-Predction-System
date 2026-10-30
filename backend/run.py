"""Start the backend. Usage (from the project root): .venv\\Scripts\\python.exe backend\\run.py

Use this instead of the bare ``uvicorn`` command: aiomqtt needs a selector event
loop, and Windows defaults to the proactor loop (design §2.2).
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root

import uvicorn  # noqa: E402

from backend.app.settings import ConfigError, get_config  # noqa: E402


def main() -> None:
    try:
        config = get_config()
    except ConfigError as exc:
        print(f"Configuration error — backend not started.\n{exc}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=config.env.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    server = uvicorn.Server(
        uvicorn.Config(
            "backend.app.main:app",
            host=config.env.backend_host,
            port=config.env.backend_port,
            log_level=config.env.log_level.lower(),
        )
    )
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
