"""Replace an HTTP worker while keeping its listening socket open."""

import logging
import os
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

LOG = logging.getLogger(__name__)
WORKER_FDS = "PAPER_SERVER_WORKER_FDS"
STARTUP_TIMEOUT = 120
POLL_INTERVAL = 0.2


def supervise(port):
    logging.basicConfig(level=logging.INFO)
    reload_requested = False
    stopping = False

    def reload_worker(signum, frame):
        nonlocal reload_requested
        reload_requested = True

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGHUP, reload_worker)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    executable = Path(sys.executable)
    active = None
    candidate = None
    readiness = None
    draining = []
    reload_requested = True
    with socket.create_server(("127.0.0.1", port)) as listener:
        # Both workers may briefly accept from this socket during handoff.
        listener.setblocking(False)
        try:
            while not stopping:
                for worker in draining[:]:
                    if worker.poll() is not None:
                        draining.remove(worker)
                        LOG.info("Drained HTTP worker %s (exit status %s).", worker.pid, worker.returncode)
                if active is not None and active.poll() is not None:
                    raise ChildProcessError(f"HTTP worker {active.pid} exited with status {active.returncode}.")
                if candidate is None and reload_requested:
                    reload_requested = False
                    readiness, notify = os.pipe()
                    try:
                        # Resolve the release symlink for each worker. Keep the venv's
                        # executable name so Python loads packages from that release.
                        command = [executable.parent.resolve() / executable.name, *sys.orig_argv[1:]]
                        candidate = subprocess.Popen(
                            command,
                            env={**os.environ, WORKER_FDS: f"{listener.fileno()},{notify}"},
                            pass_fds=(listener.fileno(), notify),
                        )
                    except OSError:
                        if active is None:
                            raise
                        LOG.exception("Could not launch the replacement HTTP worker. Keeping worker %s.", active.pid)
                        os.close(readiness)
                        readiness = None
                    finally:
                        os.close(notify)
                    deadline = time.monotonic() + STARTUP_TIMEOUT
                if candidate is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                readable, _, _ = select.select([readiness], [], [], POLL_INTERVAL)
                if readable and os.read(readiness, 1) == b"1" and candidate.poll() is None:
                    previous, active = active, candidate
                    LOG.info("HTTP worker %s ready on port %s.", active.pid, listener.getsockname()[1])
                    if previous is not None:
                        draining.append(previous)
                        previous.terminate()
                        LOG.info("Draining HTTP worker %s.", previous.pid)
                elif readable or time.monotonic() >= deadline:
                    candidate.kill()
                    candidate.wait()
                    if active is None:
                        raise ChildProcessError("HTTP worker failed to start.")
                    LOG.error("Replacement HTTP worker failed to start. Keeping worker %s.", active.pid)
                else:
                    continue
                candidate = None
                os.close(readiness)
                readiness = None
        finally:
            if readiness is not None:
                os.close(readiness)
            workers = [worker for worker in (candidate, active, *draining) if worker is not None]
            for worker in workers:
                worker.terminate()
            for worker in workers:
                worker.wait()
