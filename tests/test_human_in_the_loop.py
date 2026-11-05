"""Branch human-in-the-loop: a person submits every application; the agent gets only the browser.

The apply agent reads untrusted job pages with bypassPermissions, so what it CAN call matters
more than what the prompt asks of it: no mailbox, no shell, no file writes, none of the user's
own MCP servers. And whatever the caller passes, it fills the form and stops before Submit.
"""

import copy
from pathlib import Path
from unittest import mock

import pytest

from applypilot import config
from applypilot.apply import launcher
from applypilot.apply import prompt as pm

PROFILE = {
    "personal": {"full_name": "Alex Doe", "email": "alex@example.com", "phone": "",
                 "city": "", "country": "Kazakhstan", "password": ""},
    "work_authorization": {"legally_authorized_to_work": False, "require_sponsorship": True,
                           "work_permit_type": ""},
    "compensation": {"salary_expectation": "100000", "salary_currency": "USD"},
    "experience": {"years_of_experience_total": "10", "target_role": "AI Engineer"},
    "availability": {"earliest_start_date": "Immediately"},
}


def _prompt(dry_run: bool) -> str:
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    resume = config.APP_DIR / "resume"
    resume.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
    job = {"url": "https://jobs.example.com/1", "title": "AI Engineer", "site": "Acme",
           "application_url": "https://jobs.example.com/1/apply", "fit_score": 8,
           "tailored_resume_path": str(resume)}
    with mock.patch.object(pm.config, "load_profile", return_value=copy.deepcopy(PROFILE)), \
            mock.patch.object(pm.config, "load_search_config", return_value={}):
        return pm.build_prompt(job, tailored_resume="resume", dry_run=dry_run).lower()


@pytest.mark.parametrize("dry_run", [True, False])
def test_never_presses_submit_whatever_the_caller_passes(dry_run):
    assert "do not click the final submit" in _prompt(dry_run)


def test_never_logs_in_or_signs_up():
    prompt = _prompt(True)
    assert "try sign up" not in prompt and "try sign in" not in prompt
    assert "do not sign in, do not sign up" in prompt


def test_never_sends_email():
    assert "send_email" not in _prompt(True)


def test_claims_only_experience_the_resume_shows():
    prompt = _prompt(True)
    assert "sell short" not in prompt
    assert "only if the resume shows it" in prompt


def test_captcha_flow_stays_upstreams_capsolver():
    assert "api.capsolver.com" in _prompt(True)


class _Spawned(Exception):
    pass


def _claude_command() -> list[str]:
    seen = {}

    def fake_popen(cmd, *args, **kwargs):
        seen["cmd"] = cmd
        raise _Spawned()

    job = {"url": "https://x", "title": "t", "site": "s", "tailored_resume_path": None}
    with mock.patch.object(launcher.prompt_mod, "build_prompt", return_value="p"), \
            mock.patch.object(launcher, "reset_worker_dir", return_value=Path(config.APP_DIR)), \
            mock.patch.object(launcher, "update_state"), \
            mock.patch.object(launcher, "add_event"), \
            mock.patch.object(launcher.subprocess, "Popen", side_effect=fake_popen):
        launcher.run_job(job, port=9222)  # catches the error itself and reports a failed job
    return seen["cmd"]


def test_only_the_browser_mcp_server():
    assert set(launcher._make_mcp_config(9222)["mcpServers"]) == {"playwright"}
    assert "--strict-mcp-config" in _claude_command()


def test_no_shell_file_writes_or_web_fetch():
    cmd = _claude_command()
    denied = set(cmd[cmd.index("--disallowedTools") + 1].split(","))
    assert {"Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"} <= denied
