import ast
import os
import subprocess
import sys
from pathlib import Path

import fzastro_ai.runtime as runtime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_base_url_normalization_adds_openai_v1_suffix():
    cases = {
        "": "http://localhost:11434/v1",
        "http://localhost:11434": "http://localhost:11434/v1",
        "http://localhost:11434/": "http://localhost:11434/v1",
        "http://localhost:11434/v1": "http://localhost:11434/v1",
        "http://localhost:11434/v1/": "http://localhost:11434/v1",
        "https://example.test/api": "https://example.test/api/v1",
    }

    for raw_url, expected_url in cases.items():
        assert runtime.normalize_runtime_base_url(raw_url) == expected_url


def test_runtime_api_key_normalization_uses_ollama_default():
    assert runtime.normalize_runtime_api_key("") == "ollama"
    assert runtime.normalize_runtime_api_key(None) == "ollama"
    assert runtime.normalize_runtime_api_key("  test-key  ") == "test-key"


def test_runtime_ollama_detection_matches_local_and_named_endpoints():
    assert runtime.is_ollama_base_url("http://localhost:11434")
    assert runtime.is_ollama_base_url("http://127.0.0.1:11434/v1")
    assert runtime.is_ollama_base_url("http://[::1]:11434")
    assert runtime.is_ollama_base_url("https://my-ollama-proxy.example/v1")
    assert not runtime.is_ollama_base_url("https://api.openai.example/v1")


def test_local_ollama_detection_is_limited_to_auto_startable_endpoint():
    assert runtime.is_local_ollama_base_url("http://localhost:11434")
    assert runtime.is_local_ollama_base_url("http://127.0.0.1:11434/v1")
    assert runtime.is_local_ollama_base_url("http://[::1]:11434")
    assert not runtime.is_local_ollama_base_url("https://my-ollama-proxy.example/v1")
    assert not runtime.is_local_ollama_base_url("https://api.openai.example/v1")


def test_runtime_helpers_import_without_openai_client_construction():
    script = (
        "import fzastro_ai.runtime as runtime; "
        "print(runtime.normalize_runtime_base_url('http://localhost:11434'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "http://localhost:11434/v1"


def test_config_honors_fzastro_app_dir_in_fresh_process(tmp_path):
    env = os.environ.copy()
    env["FZASTRO_APP_DIR"] = str(tmp_path / "appdata")
    script = "from fzastro_ai.config import APP_DIR; print(APP_DIR)"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == str(tmp_path / "appdata")


def test_app_does_not_redefine_config_or_runtime_constants():
    app_path = PROJECT_ROOT / "fzastro_ai" / "app.py"
    module = ast.parse(app_path.read_text(encoding="utf-8"))
    forbidden_assignments = {
        "API_KEY",
        "APP_DIR",
        "BASE_URL",
        "CALIBRATION_PROFILES_FILE",
        "HISTORY_FILE",
        "KNOWLEDGE_ASSET_DIR",
        "KNOWLEDGE_DB_FILE",
        "LEGACY_MEMORY_FILE",
        "LOG_DIR",
        "LOG_FILE",
        "MEMORY_FILE",
        "WEB_IMAGE_CACHE_DIR",
    }
    forbidden_functions = {
        "is_ollama_base_url",
        "make_runtime_client",
        "normalize_runtime_api_key",
        "normalize_runtime_base_url",
    }
    assigned_names = set()
    defined_functions = set()

    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned_names.add(target.id)
        elif isinstance(node, ast.FunctionDef):
            defined_functions.add(node.name)

    assert not (assigned_names & forbidden_assignments)
    assert not (defined_functions & forbidden_functions)


def test_runtime_timeout_normalization_uses_positive_defaults():
    assert runtime.normalize_runtime_timeout("2.5") == 2.5
    assert runtime.normalize_runtime_timeout(0) == 1.0
    assert runtime.normalize_runtime_timeout("bad", default=7) == 7.0


def test_runtime_client_passes_explicit_timeout(monkeypatch):
    import types

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    client = runtime.make_runtime_client(
        "http://localhost:11434", "test-key", timeout="3.5"
    )

    assert isinstance(client, FakeOpenAI)
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "test-key"
    assert captured["timeout"] == 3.5


def test_astro_cache_honors_fzastro_app_dir_in_fresh_process(tmp_path):
    env = os.environ.copy()
    env["FZASTRO_APP_DIR"] = str(tmp_path / "appdata")
    script = (
        "from fzastro_ai.astro_tools.engine import ASTRO_CACHE_DIR; "
        "print(ASTRO_CACHE_DIR)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == str(tmp_path / "appdata" / "astro_tools")


def test_runtime_connection_error_detector_handles_chained_provider_errors():
    wrapper = RuntimeError("model discovery failed")
    wrapper.__cause__ = ConnectionRefusedError("provider refused connection")

    class APITimeoutError(Exception):
        pass

    timeout_wrapper = RuntimeError("web routing failed")
    timeout_wrapper.__cause__ = APITimeoutError("Request timed out.")

    assert runtime.is_runtime_connection_error(wrapper)
    assert runtime.is_runtime_connection_error(timeout_wrapper)
    assert runtime.is_runtime_connection_error(RuntimeError("request timed out"))
    assert not runtime.is_runtime_connection_error(ValueError("bad response shape"))


def test_runtime_model_not_found_detector_handles_openai_compatible_errors():
    class Response:
        status_code = 404
        text = '{"error": {"message": "model \'qwen3:32b\' not found"}}'

    class NotFoundError(Exception):
        status_code = 404
        response = Response()

    missing_model_error = NotFoundError("model 'qwen3:32b' not found")
    wrapper = RuntimeError("web decision failed")
    wrapper.__cause__ = missing_model_error

    assert runtime.is_runtime_model_not_found_error(wrapper)
    assert not runtime.is_runtime_model_not_found_error(
        RuntimeError("404 page not found")
    )
    assert "ollama pull qwen3:32b" in runtime.format_runtime_model_unavailable_message(
        "qwen3:32b", "http://localhost:11434/v1"
    )


def test_ollama_root_url_removes_openai_suffix():
    assert runtime.ollama_root_url("http://localhost:11434") == "http://localhost:11434"
    assert (
        runtime.ollama_root_url("http://localhost:11434/v1") == "http://localhost:11434"
    )


def test_find_ollama_executable_honors_explicit_environment_path(tmp_path, monkeypatch):
    executable_name = "ollama.exe" if sys.platform.startswith("win") else "ollama"
    executable = tmp_path / executable_name
    executable.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("FZASTRO_OLLAMA_EXE", str(executable))

    assert runtime.find_ollama_executable() == str(executable)


def test_start_ollama_server_returns_running_without_spawning(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_ollama_server_available", lambda *args, **kwargs: True
    )

    result = runtime.start_ollama_server_if_available("http://localhost:11434/v1")

    assert result.available is True
    assert result.attempted_start is False
    assert result.status == "already_running"


def test_start_ollama_server_reports_missing_install(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_ollama_server_available", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(runtime, "find_ollama_executable", lambda: None)

    result = runtime.start_ollama_server_if_available("http://localhost:11434/v1")

    assert result.available is False
    assert result.attempted_start is False
    assert result.status == "not_installed"
    assert "Ollama unavailable" in result.message


def test_start_ollama_server_does_not_spawn_when_listener_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_ollama_server_available", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *args, **kwargs: True
    )

    def fail_if_spawned(*args, **kwargs):
        raise AssertionError("should not spawn a second Ollama when the port is owned")

    monkeypatch.setattr(runtime.subprocess, "Popen", fail_if_spawned)

    result = runtime.start_ollama_server_if_available("http://localhost:11434/v1")

    assert result.available is False
    assert result.attempted_start is False
    assert result.status == "listener_present_not_ready"


def test_auto_start_ollama_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("FZASTRO_AUTO_START_OLLAMA", raising=False)
    assert runtime.should_auto_start_ollama() is True

    monkeypatch.setenv("FZASTRO_AUTO_START_OLLAMA", "0")
    assert runtime.should_auto_start_ollama() is False


def test_start_ollama_server_does_not_spawn_for_remote_ollama_proxy(monkeypatch):
    def fail_if_spawned(*args, **kwargs):
        raise AssertionError("should not spawn")

    monkeypatch.setattr(runtime.subprocess, "Popen", fail_if_spawned)

    result = runtime.start_ollama_server_if_available(
        "https://my-ollama-proxy.example/v1"
    )

    assert result.available is False
    assert result.attempted_start is False
    assert result.status == "not_local_ollama"


def test_stop_owned_ollama_on_exit_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("FZASTRO_STOP_OLLAMA_ON_EXIT", raising=False)
    assert runtime.should_stop_owned_ollama_on_exit() is True

    monkeypatch.setenv("FZASTRO_STOP_OLLAMA_ON_EXIT", "0")
    assert runtime.should_stop_owned_ollama_on_exit() is False

    monkeypatch.setenv("FZASTRO_STOP_OLLAMA_ON_EXIT", "1")
    assert runtime.should_stop_owned_ollama_on_exit() is True


def test_stop_owned_ollama_process_terminates_only_given_process():
    calls = []

    class FakeProcess:
        def __init__(self):
            self.running = True

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            calls.append("terminate")
            self.running = False

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    process = FakeProcess()

    assert runtime.stop_owned_ollama_process(process) == "stopped"
    assert calls[0] == "terminate"
    assert calls[1][0] == "wait"


def test_stop_owned_ollama_process_reports_already_exited():
    class ExitedProcess:
        def poll(self):
            return 0

    assert runtime.stop_owned_ollama_process(ExitedProcess()) == "already_exited"


def test_toggle_local_ollama_turns_running_server_off(monkeypatch):
    calls = []

    def fake_available(*args, **kwargs):
        calls.append(("available", kwargs.get("timeout")))
        return len([item for item in calls if item[0] == "available"]) == 1

    monkeypatch.setattr(runtime, "is_ollama_server_available", fake_available)
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        runtime,
        "terminate_local_ollama_server",
        lambda *args, **kwargs: (True, "stopped"),
    )

    result = runtime.toggle_local_ollama_server("http://localhost:11434/v1")

    assert result.running is False
    assert result.action == "stop"
    assert result.changed_state is True
    assert result.status == "stopped:stopped"


def test_toggle_local_ollama_starts_stopped_server(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_ollama_server_available", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        runtime,
        "start_ollama_server_if_available",
        lambda *args, **kwargs: runtime.OllamaStartResult(
            available=True,
            attempted_start=True,
            executable="ollama",
            status="started",
            message="Ollama was started automatically.",
            process=None,
        ),
    )

    result = runtime.toggle_local_ollama_server("http://localhost:11434/v1")

    assert result.running is True
    assert result.action == "start"
    assert result.changed_state is True
    assert result.status == "started:started"


def test_toggle_local_ollama_rejects_remote_proxy(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not touch remote provider")

    monkeypatch.setattr(runtime, "terminate_local_ollama_server", fail_if_called)
    monkeypatch.setattr(runtime, "start_ollama_server_if_available", fail_if_called)

    result = runtime.toggle_local_ollama_server("https://ollama.example.test/v1")

    assert result.running is False
    assert result.action == "none"
    assert result.status == "not_local_ollama"


def test_terminate_local_ollama_escalates_to_port_owner_on_windows(monkeypatch):
    commands = []
    wait_results = iter([False, True])

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: True
    )
    monkeypatch.setattr(
        runtime,
        "_wait_for_ollama_shutdown",
        lambda *a, **k: next(wait_results),
    )

    def fake_run(command, **kwargs):
        commands.append(command)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    stopped, status = runtime.terminate_local_ollama_server("http://localhost:11434/v1")

    assert stopped is True
    assert status == "killed"
    assert any(command[:3] == ["taskkill", "/IM", "ollama.exe"] for command in commands)
    assert any(
        command[:3] == ["taskkill", "/IM", "llama-server.exe"] for command in commands
    )
    assert any(command and command[0] == "powershell" for command in commands)
    joined_commands = [" ".join(command) for command in commands]
    assert any(
        "Get-NetTCPConnection -LocalPort 11434" in item for item in joined_commands
    )
    assert any("Stop-Service -Name Ollama" in item for item in joined_commands)
    assert any("llama-server" in item for item in joined_commands)


def test_ollama_http_probe_is_skipped_when_listener_is_absent(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *args, **kwargs: False
    )

    def fail_if_http_called(*args, **kwargs):
        raise AssertionError("refresh/status must not touch Ollama HTTP when offline")

    monkeypatch.setattr(runtime.requests, "get", fail_if_http_called)

    assert runtime.is_ollama_server_available("http://localhost:11434/v1") is False


def test_listener_output_parser_detects_listening_port():
    assert runtime._parse_listener_output("TCP 127.0.0.1:11434 LISTENING", 11434)
    assert runtime._parse_listener_output("tcp 0 0 127.0.0.1:11434 LISTEN", 11434)
    assert not runtime._parse_listener_output("TCP 127.0.0.1:11435 LISTENING", 11434)


def test_wait_for_ollama_shutdown_requires_stable_listener_absence(monkeypatch):
    states = iter([True, False, True, False, False, False])
    monkeypatch.setattr(
        runtime,
        "is_local_ollama_listener_present",
        lambda *args, **kwargs: next(states, False),
    )
    monkeypatch.setattr(runtime.time, "sleep", lambda *args, **kwargs: None)

    assert runtime._wait_for_ollama_shutdown(
        "http://localhost:11434/v1", timeout=2.0, stable_seconds=0.2
    )


def test_ollama_keep_alive_mode_normalization():
    assert runtime.normalize_ollama_keep_alive_mode("30m") == "30m"
    assert runtime.normalize_ollama_keep_alive_mode("ALWAYS") == "always"
    assert runtime.normalize_ollama_keep_alive_mode("bad") == "30m"
    assert runtime.ollama_keep_alive_value("default") is None
    assert runtime.ollama_keep_alive_value("30m") == "30m"
    assert runtime.ollama_keep_alive_value("always") == "-1"
    assert runtime.normalize_ollama_keep_alive_value("45m") == "45m"
    assert runtime.normalize_ollama_keep_alive_value("bad value") is None


def test_start_ollama_server_passes_keep_alive_to_owned_process(monkeypatch):
    executable = "/tmp/ollama"
    captured = {}
    checks = iter([False, True])

    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: False
    )
    monkeypatch.setattr(
        runtime, "is_ollama_server_available", lambda *a, **k: next(checks, True)
    )
    monkeypatch.setattr(runtime, "find_ollama_executable", lambda: executable)
    monkeypatch.setattr(runtime.time, "sleep", lambda *a, **k: None)

    class FakeProcess:
        pass

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        return FakeProcess()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)

    result = runtime.start_ollama_server_if_available(
        "http://localhost:11434/v1", keep_alive="60m"
    )

    assert result.available is True
    assert captured["args"] == [executable, "serve"]
    assert captured["env"]["OLLAMA_KEEP_ALIVE"] == "60m"
    assert captured["env"]["FZASTRO_OLLAMA_KEEP_ALIVE"] == "60m"


def test_apply_ollama_keep_alive_uses_native_generate_without_waking_offline_local(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: False
    )

    def fail_post(*args, **kwargs):
        raise AssertionError("offline local keep-alive apply must not touch HTTP")

    monkeypatch.setattr(runtime.requests, "post", fail_post)

    result = runtime.apply_ollama_model_keep_alive(
        "http://localhost:11434/v1", "qwen:test", "always"
    )

    assert result.applied is False
    assert result.status == "offline"


def test_ollama_keep_alive_preloads_only_warm_modes():
    assert runtime.ollama_keep_alive_preloads_model("always") is True
    assert runtime.ollama_keep_alive_preloads_model("30m") is True
    assert runtime.ollama_keep_alive_preloads_model("60m") is True
    assert runtime.ollama_keep_alive_preloads_model("default") is False
    assert runtime.ollama_keep_alive_preloads_model("unload") is False
    assert runtime.ollama_keep_alive_preloads_model(None) is False


def test_preload_ollama_model_uses_native_generate_without_waking_offline_local(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: False
    )

    def fail_post(*args, **kwargs):
        raise AssertionError("offline local preload must not touch HTTP")

    monkeypatch.setattr(runtime.requests, "post", fail_post)

    result = runtime.preload_ollama_model(
        "http://localhost:11434/v1", "qwen:test", "always"
    )

    assert result.applied is False
    assert result.status == "offline"


def test_preload_ollama_model_posts_native_generate_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: True
    )

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    result = runtime.preload_ollama_model(
        "http://localhost:11434/v1", "qwen:test", "always", timeout=12.0
    )

    assert result.applied is True
    assert result.status == "preloaded"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"] == {
        "model": "qwen:test",
        "prompt": "",
        "keep_alive": -1,
        "stream": False,
    }
    assert captured["timeout"] == 12.0


def test_preload_ollama_model_skips_unload_mode(monkeypatch):
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: True
    )

    def fail_post(*args, **kwargs):
        raise AssertionError("unload mode must not preload")

    monkeypatch.setattr(runtime.requests, "post", fail_post)

    result = runtime.preload_ollama_model(
        "http://localhost:11434/v1", "qwen:test", "unload"
    )

    assert result.applied is False
    assert result.status == "unload_mode"


def test_apply_ollama_keep_alive_posts_native_generate_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: True
    )

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(runtime.requests, "post", fake_post)

    result = runtime.apply_ollama_model_keep_alive(
        "http://localhost:11434/v1", "qwen:test", "always"
    )

    assert result.applied is True
    assert result.status == "applied"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"] == {
        "model": "qwen:test",
        "prompt": "",
        "keep_alive": -1,
        "stream": False,
    }


def test_terminate_local_ollama_force_process_stop_runs_even_without_listener(
    monkeypatch,
):
    commands = []
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(
        runtime, "is_local_ollama_listener_present", lambda *a, **k: False
    )
    monkeypatch.setattr(runtime, "_wait_for_ollama_shutdown", lambda *a, **k: True)

    def fake_run(command, **kwargs):
        commands.append(command)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    stopped, status = runtime.terminate_local_ollama_server(
        "http://localhost:11434/v1", force_process_stop=True
    )

    assert stopped is True
    assert status == "stopped_process"
    assert commands
    assert commands[0][:3] == ["pkill", "-TERM", "-f"]


def test_ollama_shutdown_process_probe_recognizes_llama_server_runner():
    assert runtime._process_name_contains_ollama_runner("llama-server.exe")
    assert runtime._process_name_contains_ollama_runner(
        r"C:\\Users\\me\\AppData\\Local\\Programs\\Ollama\\ollama.exe"
    )
    assert not runtime._process_name_contains_ollama_runner("notepad.exe")


def test_runtime_listener_probe_hides_console_windows_on_windows(monkeypatch):
    captured = {}

    class FakeStartupInfo:
        def __init__(self):
            self.dwFlags = 0

    class FakeResult:
        stdout = "LISTENING\n"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(
        runtime.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
    )
    monkeypatch.setattr(runtime.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(
        runtime.subprocess, "STARTUPINFO", FakeStartupInfo, raising=False
    )
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    assert (
        runtime._run_listener_probe_command(["powershell"], timeout=0.2)
        == "LISTENING\n"
    )
    assert captured["command"] == ["powershell"]
    assert captured["creationflags"] == 0x08000000
    assert captured["startupinfo"].dwFlags & 1
    assert captured["stdin"] is runtime.subprocess.DEVNULL
    assert captured["stderr"] is runtime.subprocess.DEVNULL
    assert captured["stdout"] is runtime.subprocess.PIPE
