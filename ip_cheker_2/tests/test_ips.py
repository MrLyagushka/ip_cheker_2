import pytest

from utils import ips


def test_single_host():
    targets, kind = ips.parse_target(" 8.8.8.8 ")
    assert targets == ["8.8.8.8"]
    assert kind == "host"


def test_subnet_expands_to_256():
    targets, kind = ips.parse_target("192.168.0.0")
    assert kind == "subnet"
    assert len(targets) == 256
    assert targets[0] == "192.168.0.0"
    assert targets[-1] == "192.168.0.255"


def test_invalid_targets():
    for bad in ("", "   ", "abc", "1.2.3", "1.2.3.4.5", "256.1.1.1", "::1", "1.2.3.4/24", "01.2.3.4"):
        with pytest.raises(ValueError):
            ips.parse_target(bad)


def test_zero_network_forbidden():
    for bad in ("0.0.0.0", "0.0.1.0", "0.0.12.34"):
        with pytest.raises(ValueError):
            ips.parse_target(bad)


def test_normal_zero_last_octet_is_subnet():
    targets, kind = ips.parse_target("10.0.0.0")
    assert kind == "subnet" and len(targets) == 256


def test_parse_single_rejects_subnet():
    assert ips.parse_single("8.8.8.8") == "8.8.8.8"
    with pytest.raises(ValueError):
        ips.parse_single("192.168.0.0")


def test_subnet_label():
    assert ips.subnet_label("192.168.0.0") == "192.168.0.0/24"
    assert ips.subnet_label("10.20.0.37") == "10.20.0.0/24"


def test_error_message_is_human_readable():
    with pytest.raises(ValueError) as exc:
        ips.parse_target("привет")
    assert "IPv4" in str(exc.value)
