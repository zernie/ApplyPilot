"""`--base-resume`: apply with ~/.applypilot/resume.pdf where no tailored resume exists."""

from applypilot import config
from applypilot.apply import launcher
from applypilot.database import get_connection, init_db


def _add_job(url, tailored=None, fit=8):
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM jobs")
    conn.execute(
        "INSERT INTO jobs (url, title, site, application_url, fit_score, tailored_resume_path)"
        " VALUES (?, 'Engineer', 'Acme', ?, ?, ?)", (url, url, fit, tailored))
    conn.commit()


def test_untailored_jobs_stay_out_of_the_queue_by_default():
    _add_job("https://example.com/jobs/1")
    assert launcher.acquire_job(min_score=7) is None


def test_base_resume_lets_untailored_jobs_through_with_the_base_resume():
    _add_job("https://example.com/jobs/2")
    job = launcher.acquire_job(min_score=7, base_resume=True)
    assert job["url"] == "https://example.com/jobs/2"
    assert job["tailored_resume_path"] == str(config.RESUME_PDF_PATH.with_suffix(""))


def test_a_tailored_resume_still_wins_over_the_base_one():
    _add_job("https://example.com/jobs/3", tailored="/tmp/tailored/acme")
    job = launcher.acquire_job(min_score=7, base_resume=True)
    assert job["tailored_resume_path"] == "/tmp/tailored/acme"


def test_a_specific_url_also_honours_base_resume():
    _add_job("https://example.com/jobs/4")
    assert launcher.acquire_job(target_url="https://example.com/jobs/4") is None
    job = launcher.acquire_job(target_url="https://example.com/jobs/4", base_resume=True)
    assert job["url"] == "https://example.com/jobs/4"


def test_a_specific_url_finds_a_job_that_was_never_tried():
    # apply_status is NULL until the first attempt, and `NULL != 'in_progress'` is not true in SQL,
    # so `--url` used to match only jobs that had already been attempted.
    _add_job("https://example.com/jobs/5", tailored="/tmp/tailored/acme")
    job = launcher.acquire_job(target_url="https://example.com/jobs/5")
    assert job["url"] == "https://example.com/jobs/5"
