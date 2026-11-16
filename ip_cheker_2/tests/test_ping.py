import asyncio

from utils import ping


class FakeProc:
    def __init__(self, returncode=0, out=b"", hang=False):
        self.returncode = returncode
        self._out = out
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(30)
        return self._out, None

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def patch_exec(monkeypatch, procs):
    created = []

    async def fake_exec(*cmd, **kwargs):
        created.append(cmd)
        proc = procs[cmd[-1]]
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr(ping.asyncio, "create_subprocess_exec", fake_exec)
    return created


def test_alive_and_dead_by_returncode(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", False)
    patch_exec(monkeypatch, {"1.1.1.1": FakeProc(0), "2.2.2.2": FakeProc(1)})

    async def scenario():
        return await ping.ping_one("1.1.1.1"), await ping.ping_one("2.2.2.2")

    assert asyncio.run(scenario()) == (("1.1.1.1", True), ("2.2.2.2", False))


def test_linux_command_flags(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", False)
    assert ping.build_cmd("1.1.1.1") == ["ping", "-c", "1", "-W", "1", "1.1.1.1"]


def test_windows_command_flags(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", True)
    assert ping.build_cmd("1.1.1.1") == ["ping", "-n", "1", "-w", "1000", "1.1.1.1"]


def test_windows_needs_ttl(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", True)
    patch_exec(monkeypatch, {
        "1.1.1.1": FakeProc(0, b"Reply from 1.1.1.1: bytes=32 time=1ms TTL=57"),
        "2.2.2.2": FakeProc(0, b"Reply from 1.1.1.1: Destination host unreachable."),
    })

    async def scenario():
        return await ping.ping_one("1.1.1.1"), await ping.ping_one("2.2.2.2")

    assert asyncio.run(scenario()) == (("1.1.1.1", True), ("2.2.2.2", False))


def test_timeout_kills_process(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", False)
    monkeypatch.setattr(ping, "TIMEOUT", 0.05)
    proc = FakeProc(0, hang=True)
    patch_exec(monkeypatch, {"1.1.1.1": proc})
    assert asyncio.run(ping.ping_one("1.1.1.1")) == ("1.1.1.1", False)
    assert proc.killed is True


def test_subprocess_error_is_dead_not_crash(monkeypatch):
    monkeypatch.setattr(ping, "IS_WINDOWS", False)
    patch_exec(monkeypatch, {"1.1.1.1": OSError("ping not found")})
    assert asyncio.run(ping.ping_one("1.1.1.1")) == ("1.1.1.1", False)


def test_ping_many_respects_limit(monkeypatch):
    active = 0
    peak = 0

    async def fake_ping(ip):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ip, True

    monkeypatch.setattr(ping, "ping_one", fake_ping)
    ips = [f"10.0.0.{i}" for i in range(1, 21)]
    results = asyncio.run(ping.ping_many(ips, limit=3))
    assert len(results) == 20
    assert all(results.values())
    assert peak <= 3


def test_ping_many_empty():
    assert asyncio.run(ping.ping_many([], limit=5)) == {}


def test_ping_many_cancel_skips_rest(monkeypatch):
    cancel = asyncio.Event()
    calls = []

    async def fake_ping(ip):
        calls.append(ip)
        if len(calls) == 2:
            cancel.set()
        return ip, True

    monkeypatch.setattr(ping, "ping_one", fake_ping)
    ips = [f"10.0.0.{i}" for i in range(1, 51)]
    results = asyncio.run(ping.ping_many(ips, limit=1, cancel=cancel))
    assert len(results) < len(ips)
    assert cancel.is_set()


def test_ping_many_progress_reports_final(monkeypatch):
    async def fake_ping(ip):
        return ip, True

    monkeypatch.setattr(ping, "ping_one", fake_ping)
    monkeypatch.setattr(ping, "PROGRESS_EVERY", 0)  # чтобы отчёт был на каждом шаге
    seen = []

    async def progress(done, total):
        seen.append((done, total))

    ips = [f"10.0.0.{i}" for i in range(1, 6)]
    asyncio.run(ping.ping_many(ips, limit=2, progress=progress))
    assert seen[-1] == (5, 5)


def test_progress_is_throttled(monkeypatch):
    async def fake_ping(ip):
        return ip, True

    monkeypatch.setattr(ping, "ping_one", fake_ping)
    monkeypatch.setattr(ping, "PROGRESS_EVERY", 3600)
    seen = []

    async def progress(done, total):
        seen.append(done)

    asyncio.run(ping.ping_many([f"10.0.0.{i}" for i in range(1, 30)], limit=4, progress=progress))
    assert seen == [29]  # только финальный отчёт, без 29 редактирований сообщения
