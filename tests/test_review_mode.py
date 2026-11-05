"""`applypilot apply --review`: the agent fills, a person checks the open window and submits."""

from unittest import mock

import pytest
from typer.testing import CliRunner

from applypilot.apply import review
from applypilot.cli import app


class _Queue:
    """Stand-ins for the launcher/chrome functions the review loop calls, with a call log."""

    def __init__(self, jobs, agent_results=None):
        self.jobs = list(jobs)
        self.agent_results = list(agent_results or ["applied"] * len(self.jobs))
        self.log = []

    def acquire_job(self, target_url=None, min_score=7, worker_id=0, base_resume=False):
        self.log.append(("acquire", base_resume))
        return self.jobs.pop(0) if self.jobs else None

    def launch_chrome(self, worker_id, port=None, headless=False):
        self.log.append(("chrome", headless))
        return "proc"

    def run_job(self, job, port, worker_id=0, model="sonnet", dry_run=False):
        self.log.append(("agent", job["url"], dry_run))
        result = self.agent_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result, 1000

    def mark_result(self, url, status, **kwargs):
        self.log.append(("applied", url, status))

    def release_lock(self, url):
        self.log.append(("released", url))

    def cleanup_worker(self, worker_id, proc):
        self.log.append(("closed", proc))


def _run(queue, answers, **kwargs):
    answers = list(answers)
    asked = []

    def ask(prompt):
        asked.append(queue.log[-1])  # what had happened when the question was asked
        return answers.pop(0)

    with mock.patch.multiple(review.launcher, acquire_job=queue.acquire_job, run_job=queue.run_job,
                             mark_result=queue.mark_result, release_lock=queue.release_lock), \
            mock.patch.multiple(review.chrome, launch_chrome=queue.launch_chrome,
                                cleanup_worker=queue.cleanup_worker):
        totals = review.review_loop(ask=ask, out=lambda *a, **k: None, **kwargs)
    return totals, asked


JOB_A = {"url": "https://example.com/a", "title": "A", "site": "Acme"}
JOB_B = {"url": "https://example.com/b", "title": "B", "site": "Beta"}


def test_yes_marks_applied_and_the_window_stays_open_until_answered():
    queue = _Queue([JOB_A])
    totals, asked = _run(queue, ["y"])
    assert ("agent", JOB_A["url"], True) in queue.log           # agent never submits
    assert ("chrome", False) in queue.log                       # a window the person can see
    assert asked == [("agent", JOB_A["url"], True)]             # asked before anything closed
    applied_at = queue.log.index(("applied", JOB_A["url"], "applied"))
    assert applied_at < queue.log.index(("closed", "proc"))
    assert totals == {"submitted": 1, "not_submitted": 0}


def test_no_puts_the_job_back_in_the_queue_and_moves_on():
    queue = _Queue([JOB_A, JOB_B])
    totals, _ = _run(queue, ["n", "y"])
    assert ("released", JOB_A["url"]) in queue.log
    assert ("applied", JOB_B["url"], "applied") in queue.log
    assert totals == {"submitted": 1, "not_submitted": 1}


def test_quit_stops_after_the_current_job():
    queue = _Queue([JOB_A, JOB_B])
    totals, _ = _run(queue, ["q"])
    assert ("released", JOB_A["url"]) in queue.log
    assert not any(entry[0] == "agent" and entry[1] == JOB_B["url"] for entry in queue.log)
    assert totals == {"submitted": 0, "not_submitted": 1}


def test_an_agent_crash_releases_the_job_and_closes_the_window():
    queue = _Queue([JOB_A], agent_results=[RuntimeError("agent died")])
    with pytest.raises(RuntimeError):
        _run(queue, [])
    assert ("released", JOB_A["url"]) in queue.log
    assert queue.log[-1] == ("closed", "proc")


def test_base_resume_reaches_the_queue():
    queue = _Queue([])
    _run(queue, [], base_resume=True)
    assert queue.log == [("acquire", True)]


@pytest.mark.parametrize("extra", [["--headless"], ["--workers", "2"], ["--continuous"]])
def test_review_refuses_options_that_hide_the_window_or_run_several_jobs_at_once(extra):
    result = CliRunner().invoke(app, ["apply", "--review", *extra])
    assert result.exit_code == 1
    assert "--review" in result.output
