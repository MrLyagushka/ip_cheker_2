import json

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


def test_settings_defaults(data):
    settings = config.load_settings()
    assert settings["ping_limit"] == config.PING_LIMIT_DEFAULT


def test_settings_merge_and_clamp(data):
    config.SETTINGS_FILE.write_text(json.dumps({"ping_limit": 9999, "proxy": "socks5://h:1"}), "utf-8")
    settings = config.load_settings()
    assert settings["ping_limit"] == config.PING_LIMIT_MAX
    assert settings["proxy"] == "socks5://h:1"

    config.SETTINGS_FILE.write_text(json.dumps({"ping_limit": 0}), "utf-8")
    assert config.load_settings()["ping_limit"] == 1

    config.SETTINGS_FILE.write_text(json.dumps({"ping_limit": "мусор"}), "utf-8")
    assert config.load_settings()["ping_limit"] == config.PING_LIMIT_DEFAULT


def test_settings_broken_file_falls_back(data):
    config.SETTINGS_FILE.write_text("{не json", "utf-8")
    assert config.load_settings()["ping_limit"] == config.PING_LIMIT_DEFAULT


def test_admin_and_alert_ids_from_env():
    assert config.ADMIN_ID == 1
    assert config.ALERT_CHAT_ID == -1001
