from datetime import UTC, datetime, timedelta

from app.services.esi import IndustryJobEntry
from app.services.industry import job_progress_percentage


def _job(start: datetime, end: datetime) -> IndustryJobEntry:
    return IndustryJobEntry(
        job_id=1,
        activity_id=1,
        blueprint_type_id=588,
        product_type_id=587,
        facility_id=60003760,
        runs=1,
        status="active",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )


def test_job_progress_percentage_halfway() -> None:
    now = datetime.now(UTC)
    job = _job(now - timedelta(minutes=30), now + timedelta(minutes=30))

    percentage = job_progress_percentage(job)

    assert 45 < percentage < 55


def test_job_progress_percentage_clamps_to_100_when_overdue() -> None:
    now = datetime.now(UTC)
    job = _job(now - timedelta(hours=2), now - timedelta(hours=1))

    assert job_progress_percentage(job) == 100.0


def test_job_progress_percentage_clamps_to_0_when_not_started() -> None:
    now = datetime.now(UTC)
    job = _job(now + timedelta(hours=1), now + timedelta(hours=2))

    assert job_progress_percentage(job) == 0.0
