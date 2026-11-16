import config


def test_parse_env_comments_quotes_and_spaces():
    text = '# комментарий\n\nTOKEN=abc\nADMIN_ID = 42 \nPROXY_URL="socks5://h:1"\nEMPTY=\nмусор\n'
    assert config.parse_env(text) == {
        "TOKEN": "abc",
        "ADMIN_ID": "42",
        "PROXY_URL": "socks5://h:1",
        "EMPTY": "",
    }


def test_parse_env_single_quotes_and_equals_in_value():
    assert config.parse_env("A='x y'\nB=socks5://u:p@h:1") == {"A": "x y", "B": "socks5://u:p@h:1"}


def test_to_int_never_raises():
    assert config.to_int(" 7 ", 0) == 7
    assert config.to_int("abc", 5) == 5
    assert config.to_int(None, 3) == 3
    assert config.to_int("", 4) == 4


def test_unquote_removes_wrapping_quotes():
    assert config.unquote('"socks5://u:p@h:1"') == "socks5://u:p@h:1"
    assert config.unquote("'socks5://u:p@h:1'") == "socks5://u:p@h:1"
    assert config.unquote("  socks5://u:p@h:1  ") == "socks5://u:p@h:1"
    assert config.unquote("socks5://u:p@h:1") == "socks5://u:p@h:1"
    assert config.unquote("") == ""


def test_env_value_with_quotes_is_cleaned(monkeypatch):
    """Главная причина «бот не стартует в Docker»: кавычки доезжают из env_file."""
    monkeypatch.setenv("PROXY_URL", '"socks5://admin:secret@162.35.229.164:1080"')
    assert config._get("PROXY_URL") == "socks5://admin:secret@162.35.229.164:1080"
    from aiohttp_socks.utils import parse_proxy_url

    proxy_type, host, port, login, password = parse_proxy_url(config._get("PROXY_URL"))
    assert (host, port, login) == ("162.35.229.164", 1080, "admin")


def test_clamp_limit():
    assert config.clamp_limit(64) == 64
    assert config.clamp_limit(0) == 1
    assert config.clamp_limit(9999) == config.PING_LIMIT_MAX
    assert config.clamp_limit("мусор") == config.PING_LIMIT_DEFAULT


def test_proxy_network_defaults():
    assert config.PROXY_PORT == 1080
    assert config.PROXY_CHECK_INTERVAL == 60
    assert config.PROXY_WAIT_HOURS == 24


def test_admin_and_alert_ids_from_env():
    assert config.ADMIN_ID == 1
    assert config.ALERT_CHAT_ID == -1001
