"""
Playwright end-to-end fixtures for the Party Check-In Streamlit app.

SAFETY
------
The project's own `.streamlit/secrets.toml` (if present) points at a
production Supabase database and real Gmail SMTP credentials. Streamlit
resolves `st.secrets` relative to the process's current working directory,
so this suite:

  1. Never launches `streamlit run` with the project directory as cwd — the
     app subprocess always runs with cwd = a throwaway temp directory that
     has its own `.streamlit/secrets.toml` (sqlite DB, blank MAIL_* so no
     mail is ever sent, a known ADMIN_PASSWORD).
  2. Isolates *this* pytest process's own `st.secrets` resolution the same
     way before it ever imports `utils`/`config` directly (used to seed/reset
     the DB without going through the UI) — see the `db` fixture docstring
     for exactly why the import ordering there matters.
  3. Hard-asserts the resulting DB engine is sqlite before any seed/reset
     code runs, as a last-resort safety net.

Run with:  <python> -m pytest tests/e2e -v
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

PROJECT_DIR = Path(__file__).resolve().parents[2]

# Known values baked into the sandbox secrets.toml — imported by test modules
# that need them (e.g. the admin password, or the ticket price for computing
# expected totals) without ever touching the real project secrets.
ADMIN_PASSWORD = "e2e-sandbox-admin-pw-9f3a1c"
ZELLE_INFO_TEST = "test-zelle@example.com"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: exercises a real wait (e.g. a cache TTL) — slower but not flaky")


def _free_port() -> int:
    """Ask the OS for an unused TCP port rather than hardcoding one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _terminate(proc: subprocess.Popen) -> None:
    """Kill the process (and its whole process group) if still alive."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Sandbox: throwaway cwd + secrets.toml + running Streamlit subprocess
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sandbox_dir(tmp_path_factory):
    """A throwaway directory with its own .streamlit/secrets.toml.

    DATABASE_URL is an ABSOLUTE sqlite path, so every later connection to it
    (from either this pytest process or the app subprocess) resolves to the
    exact same file regardless of whichever process's cwd is active at
    connect time.
    """
    d = tmp_path_factory.mktemp("pc_e2e_sandbox")
    st_dir = d / ".streamlit"
    st_dir.mkdir(parents=True, exist_ok=True)
    db_path = d / "local_e2e.db"
    secrets = f'''DATABASE_URL = "sqlite:///{db_path}"
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
ADMIN_PASSWORD = "{ADMIN_PASSWORD}"
ZELLE_INFO = "{ZELLE_INFO_TEST}"
'''
    (st_dir / "secrets.toml").write_text(secrets)
    return d


@pytest.fixture(scope="session")
def base_url(sandbox_dir):
    """Start `streamlit run` with cwd = sandbox_dir (NEVER the project dir)
    on a dynamically-picked free port. Tears the process (and any children)
    down on session teardown."""
    port = _free_port()
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(PROJECT_DIR / "streamlit_app.py"),
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.runOnSave", "false",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(sandbox_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,  # own process group -> clean teardown, no stray children
    )

    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    started = False
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"streamlit process exited early (code={proc.returncode}):\n{out}"
            )
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    started = True
                    break
        except URLError:
            pass
        time.sleep(0.5)

    if not started:
        _terminate(proc)
        raise RuntimeError(f"Streamlit did not come up at {url} within 60s")

    yield url

    _terminate(proc)


# ─────────────────────────────────────────────────────────────────────────
# Direct DB access for seeding/resetting (bypasses the UI for speed)
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db(sandbox_dir, base_url):
    """Import utils/config for direct DB seeding, isolated from the real
    project secrets.

    Streamlit computes its default secrets-file *search path* exactly once,
    from `os.getcwd()` at the moment `streamlit.config` is first imported in
    a process (`file_util.get_project_streamlit_file_path` calls
    `Path.cwd()` at import time, and the result is baked into a module-level
    default_val list). If that first import happened while this process's
    cwd was the project directory, this driver process would resolve
    PROJECT_DIR/.streamlit/secrets.toml -- the production Supabase/SMTP
    credentials -- for every `st.secrets` access for the rest of the run.

    So we chdir into the sandbox for the FIRST import of `utils` (which is
    what pulls in `streamlit` for the first time in this process) and only
    that first import; we restore the original cwd immediately after. Since
    sandbox_dir's DATABASE_URL is an absolute path, every later DB
    connection resolves the exact same file regardless of cwd at that point.

    Belt-and-suspenders: we still hard-assert the resulting engine is
    sqlite before returning, so a mistake here fails loudly instead of
    silently touching a real database.
    """
    prev_cwd = os.getcwd()
    os.chdir(sandbox_dir)
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        import utils as _utils
        import config as _config  # noqa: F401 -- imported for parity / to prime it safely too
    finally:
        os.chdir(prev_cwd)

    engine_url = str(_utils.get_engine().url)
    assert engine_url.startswith("sqlite"), (
        f"SAFETY ABORT: e2e DB engine resolved to a non-sqlite URL ({engine_url}). "
        "Refusing to seed/reset -- this would touch a real database."
    )
    _utils.init_db()
    return _utils


@pytest.fixture(scope="session")
def app_config(db):
    """The `config` module, already safely imported by the `db` fixture."""
    return sys.modules["config"]


@pytest.fixture()
def reset_db(db):
    """Function-scoped: wipe all app tables before each test for a clean slate.

    Includes `app_settings` (the check-in mode override, see
    `force_checkin_open` below) — without this, one test flipping the
    check-in mode (via the admin UI or `force_checkin_open`) would leak
    into whichever test runs next, since AppSetting rows are otherwise
    untouched by any per-test reset and would silently make the suite
    order-dependent.
    """
    session = db.get_db()
    try:
        session.query(db.CheckInLog).delete()
        session.query(db.SubmissionLog).delete()
        session.query(db.PageVisit).delete()
        session.query(db.Guest).delete()
        session.query(db.AppSetting).delete()
        session.commit()
    finally:
        session.close()
    return db


@pytest.fixture()
def force_checkin_open(reset_db):
    """Force the check-in window open by writing the `app_settings` row
    directly via the service layer — mirrors `seed_guest`'s
    bypass-the-UI pattern. The event date is always far in the future
    relative to whenever this suite runs, so the default 'auto' mode is
    closed; scanner tests that need an open window use this fixture rather
    than depending on the real event date/time."""
    reset_db.set_checkin_mode(reset_db.CHECKIN_MODE_OPEN)
    return reset_db


@pytest.fixture()
def seed_guest(reset_db):
    """Factory fixture: create a guest directly via the service layer
    (bypasses the UI/HTTP entirely, so it's fast and doesn't depend on any
    widget selectors)."""

    def _make(**kwargs):
        # Phone is mandatory at registration, so seeded guests carry one too.
        # Pass a distinct `phone=` in any test that looks a guest up by number
        # — the default is shared, and get_guest_by_phone returns the most
        # recent registration on a collision.
        defaults = dict(
            name="Seed Guest", email="seed.guest@example.com", phone="+1-555-200-0000",
            ticket_count=1, plus_one_name="", zelle_ref="ZELLE-SEED0001",
        )
        defaults.update(kwargs)
        result = reset_db.register_guest(
            defaults["name"], defaults["email"], defaults["phone"],
            defaults["ticket_count"], defaults["plus_one_name"], defaults["zelle_ref"],
        )
        assert result["ok"], result
        return result["guest"]

    return _make


# ─────────────────────────────────────────────────────────────────────────
# Playwright browser / context / page
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance):
    b = playwright_instance.chromium.launch()
    yield b
    b.close()


@pytest.fixture()
def context(browser):
    """Function-scoped: a fresh browser context per test means a fresh
    Streamlit session (new websocket -> new st.session_state), which is
    what keeps tests independent of run order."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
    yield ctx
    ctx.close()


@pytest.fixture()
def page(context):
    p = context.new_page()
    yield p
    p.close()


@pytest.fixture()
def mobile_context(browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    yield ctx
    ctx.close()


@pytest.fixture()
def mobile_page(mobile_context):
    p = mobile_context.new_page()
    yield p
    p.close()
