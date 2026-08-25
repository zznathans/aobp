from datetime import UTC, datetime

from app.services.esi import IndustryJobEntry

ACTIVITY_NAMES = {
    1: "Manufacturing",
    3: "Time Efficiency Research",
    4: "Material Efficiency Research",
    5: "Copying",
    8: "Invention",
    9: "Reaction",
}


def job_progress_percentage(job: IndustryJobEntry) -> float:
    start = datetime.fromisoformat(job.start_date)
    end = datetime.fromisoformat(job.end_date)
    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return 100.0
    elapsed_seconds = (datetime.now(UTC) - start).total_seconds()
    return max(0.0, min(100.0, 100.0 * elapsed_seconds / total_seconds))
