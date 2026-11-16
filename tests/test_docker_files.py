"""Docker-файлы: проверяем то, что реально ломается в контейнере."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text("utf-8")


def test_dockerfile_installs_ping_and_runs_non_root():
    body = read("Dockerfile")
    assert "iputils-ping" in body          # без него ICMP невозможен
    assert "USER appuser" in body
    assert "DATA_DIR=/app/data" in body
    assert 'CMD ["python", "main.py"]' in body


def test_dockerfile_copies_code_selectively():
    body = read("Dockerfile")
    for folder in ("handlers/", "middlewares/", "keyboards/", "utils/"):
        assert f"COPY {folder}" in body
    assert "COPY . ." not in body          # иначе в образ уедут .env и data
    assert "tests" not in body


def test_dockerignore_hides_secrets_and_runtime():
    body = read(".dockerignore")
    for entry in (".env", "data/", "venv/", "__pycache__/", "*.log"):
        assert entry in body


def test_compose_structure():
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load(read("docker-compose.yml"))
    service = compose["services"]["bot"]
    assert service["restart"] == "unless-stopped"
    assert service["init"] is True                      # сбор зомби-ping и SIGTERM
    assert service["env_file"] == ".env"                # секреты не в образе
    assert service["environment"]["DATA_DIR"] == "/app/data"
    assert service["sysctls"]["net.ipv4.ping_group_range"] == "0 2147483647"
    assert "host.docker.internal:host-gateway" in service["extra_hosts"]
    assert "bot_data:/app/data" in service["volumes"]
    assert "bot_data" in compose["volumes"]


def test_compose_has_no_hardcoded_secrets():
    body = read("docker-compose.yml")
    for word in ("TOKEN=", "AA", "socks5://user:pass"):
        assert word not in body


def test_env_example_documents_thread_and_proxy():
    body = read(".env.example")
    assert "ALERT_THREAD_ID" in body
    assert "PROXY_URL" in body


def test_every_copy_source_exists():
    """Опечатка в COPY = падение сборки. Проверяем заранее."""
    for line in read("Dockerfile").splitlines():
        if not line.startswith("COPY "):
            continue
        parts = line.split()[1:-1]  # последнее — назначение в образе
        for source in parts:
            assert (ROOT / source).exists(), f"COPY {source}: файла нет"


def test_dockerignore_does_not_hide_needed_sources():
    ignored = set(read(".dockerignore").split())
    for needed in ("main.py", "config.py", "requirements.txt", "handlers/", "utils/", "keyboards/", "middlewares/"):
        assert needed not in ignored
