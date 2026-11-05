"""Review mode: the agent fills one application, a person checks it and submits it.

``applypilot apply --review`` runs one visible Chrome window at a time. The agent fills the form
and stops before the final Submit (dry run). The window stays open while the terminal asks whether
the person submitted it themselves:

    y  submitted       -> the job is marked applied
    n  not submitted   -> the job goes back to the queue
    q  quit            -> stop after this job (counts as not submitted)

Only then is the window closed. One worker and no live dashboard: a terminal prompt and the
dashboard cannot share the screen.
"""

from __future__ import annotations

from collections.abc import Callable

from applypilot.apply import chrome, launcher

QUESTION = (
    "\n  The form is filled in the Chrome window. Check it, solve a CAPTCHA if one is there,\n"
    "  press Submit yourself, then answer here.\n"
    "  Submitted? [y]es / [n]o / [q]uit: "
)


def review_loop(target_url: str | None = None, min_score: int = 7, model: str = "sonnet",
                base_resume: bool = False, ask: Callable[[str], str] = input,
                out: Callable[..., None] = print) -> dict:
    """Fill jobs one at a time; a person decides each one. Returns the two counts."""
    totals = {"submitted": 0, "not_submitted": 0}
    port = launcher.BASE_CDP_PORT  # worker 0: Chrome and the agent must use the same port
    while True:
        job = launcher.acquire_job(target_url=target_url, min_score=min_score, worker_id=0,
                                   base_resume=base_resume)
        if not job:
            out("Queue empty.")
            return totals
        out(f"\n=== {job.get('title')} - {job.get('site')}\n"
            f"    {job.get('application_url') or job['url']}")
        proc = chrome.launch_chrome(0, port=port, headless=False)
        answer = "n"
        try:
            result, _duration_ms = launcher.run_job(job, port=port, worker_id=0, model=model,
                                                    dry_run=True)
            out(f"    agent: {result}")
            answer = (ask(QUESTION) or "n").strip().lower()[:1]
        finally:
            if answer == "y":
                launcher.mark_result(job["url"], "applied")
                totals["submitted"] += 1
            else:
                launcher.release_lock(job["url"])
                totals["not_submitted"] += 1
            chrome.cleanup_worker(0, proc)
        if answer == "q" or target_url:
            return totals
