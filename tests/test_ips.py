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


def test_parse_targets_multiple_hosts():
    addresses, kind, label = ips.parse_targets("8.8.8.8 1.1.1.1   9.9.9.9")
    assert addresses == ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
    assert kind == "multi"
    assert label == "8.8.8.8, 1.1.1.1, 9.9.9.9"


def test_parse_targets_dedupes():
    addresses, kind, label = ips.parse_targets("8.8.8.8 8.8.8.8")
    assert addresses == ["8.8.8.8"]
    assert kind == "host" and label == "8.8.8.8"


def test_parse_targets_mixed_subnet_and_hosts():
    addresses, kind, label = ips.parse_targets("8.8.8.8 192.168.0.0")
    assert len(addresses) == 257
    assert kind == "multi"
    assert label == "8.8.8.8, 192.168.0.0/24"


def test_parse_targets_accepts_commas():
    assert ips.parse_targets("8.8.8.8,1.1.1.1;9.9.9.9")[0] == ["8.8.8.8", "1.1.1.1", "9.9.9.9"]


def test_parse_targets_names_bad_token():
    with pytest.raises(ValueError) as exc:
        ips.parse_targets("8.8.8.8 привет")
    assert "привет" in str(exc.value)


def test_parse_targets_limit(monkeypatch):
    import config

    monkeypatch.setattr(config, "SCAN_MAX_IPS", 10)
    with pytest.raises(ValueError) as exc:
        ips.parse_targets("192.168.0.0")
    assert "Лимит" in str(exc.value)


def test_parse_targets_empty():
    with pytest.raises(ValueError):
        ips.parse_targets("   ")


def test_parse_host_port():
    assert ips.parse_host_port("162.35.229.164") == ("162.35.229.164", None)
    assert ips.parse_host_port(" 162.35.229.164:1080 ") == ("162.35.229.164", 1080)


def test_parse_host_port_rejects_garbage():
    for bad in ("", "привет", "1.2.3.4:abc", "1.2.3.4:0", "1.2.3.4:99999", "192.168.0.0", "1.2.3.4 5.6.7.8"):
        with pytest.raises(ValueError):
            ips.parse_host_port(bad)
