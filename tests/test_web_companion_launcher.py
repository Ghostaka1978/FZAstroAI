from fzastro_ai.web_companion import launcher


class FakeOwnedProcess:
    def __init__(self, pid=4321, exit_on_terminate=True):
        self.pid = pid
        self.exit_on_terminate = exit_on_terminate
        self.killed = False
        self.terminated = False
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        return None

    def terminate(self):
        self.terminated = True
        if self.exit_on_terminate:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise launcher.subprocess.TimeoutExpired("web", timeout)
        return self.returncode


def test_owned_web_companion_stop_kills_unresponsive_child(monkeypatch):
    process = FakeOwnedProcess(exit_on_terminate=False)
    companion = launcher.WebCompanionProcess(port=7860)
    companion.process = process

    monkeypatch.setattr(launcher, "is_web_companion_available", lambda port: False)

    status = companion.stop(force_external=True)

    assert process.terminated is True
    assert process.killed is True
    assert companion.process is None
    assert status.running is False
    assert "Stopped Web Companion process" in status.message


def test_web_companion_stop_force_external_when_health_remains(monkeypatch):
    process = FakeOwnedProcess(pid=1111)
    companion = launcher.WebCompanionProcess(port=7860)
    companion.process = process

    calls = {"health": 0, "terminated": None}

    def fake_available(port):
        calls["health"] += 1
        # Keep health alive until the external listener termination path runs.
        return calls["terminated"] is None

    def fake_find_pids(port):
        return {2222}

    def fake_terminate_pids(pids):
        calls["terminated"] = set(pids)
        return set(pids), set()

    monkeypatch.setattr(launcher, "is_web_companion_available", fake_available)
    monkeypatch.setattr(launcher, "find_web_companion_listener_pids", fake_find_pids)
    monkeypatch.setattr(launcher, "terminate_listener_pids", fake_terminate_pids)

    status = companion.stop(force_external=True)

    assert process.terminated is True
    assert companion.process is None
    assert calls["terminated"] == {2222}
    assert status.running is False
    assert "Stopped Web Companion process 1111" in status.message


def test_external_web_companion_stop_can_leave_manual_process_alone(monkeypatch):
    companion = launcher.WebCompanionProcess(port=7860)

    monkeypatch.setattr(launcher, "is_web_companion_available", lambda port: True)

    status = companion.stop(force_external=False)

    assert status.running is True
    assert status.owned is False
    assert "started manually" in status.message
