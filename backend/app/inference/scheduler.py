"""Hourly prediction job (FR-INF-01, design §10.1).

Runs at ``prediction.run_cron_minute`` past every site-local hour, 30 s late so
the reading that closes the hour has time to arrive.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app.settings import SiteConfig

log = logging.getLogger(__name__)

JOB_ID = "hourly-prediction"
DELAY_S = 30
MISFIRE_GRACE_S = 300


class PredictionScheduler:
    def __init__(self, site: SiteConfig, runner) -> None:
        self._site = site
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone=site.site.timezone)

    def start(self) -> None:
        trigger = CronTrigger(
            minute=self._site.prediction.run_cron_minute,
            second=DELAY_S,
            timezone=self._site.site.timezone,
        )
        self._scheduler.add_job(
            self._runner.run,
            trigger,
            id=JOB_ID,
            misfire_grace_time=MISFIRE_GRACE_S,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info("Hourly predictions scheduled; next run %s", self.next_run_time)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    @property
    def running(self) -> bool:
        return self._scheduler.running

    @property
    def next_run_time(self) -> datetime | None:
        job = self._scheduler.get_job(JOB_ID)
        return job.next_run_time if job else None
