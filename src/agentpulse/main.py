from __future__ import annotations

import logging

import uvicorn

from .config import settings
from .db import init_db
from .distribution.site import create_app
from .scheduler import create_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")


def main() -> None:
    init_db()
    app = create_app()
    scheduler = create_scheduler()
    scheduler.start()
    uvicorn.run(app, host=settings.site_host, port=settings.site_port, log_level="info")


if __name__ == "__main__":
    main()