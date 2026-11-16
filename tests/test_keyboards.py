from keyboards import inline


def buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_main_menu():
    data = {button.callback_data for button in buttons(inline.main_menu())}
    assert data == {"scan:start", "hist:show", "mon:list", "help"}


def test_myips_callback_data_fits_telegram_limit():
    items = [{"ip": f"10.0.0.{i}", "status": "up"} for i in range(20)]
    markup = inline.myips(items)
    all_buttons = buttons(markup)
    for button in all_buttons:
        assert len(button.callback_data.encode("utf-8")) < 64
    removals = [b.callback_data for b in all_buttons if b.callback_data.startswith("mon:rm:")]
    assert removals == [f"mon:rm:{i}" for i in range(20)]


def test_myips_empty_list_still_has_actions():
    data = {button.callback_data for button in buttons(inline.myips([]))}
    assert data == {"mon:check", "mon:add", "menu"}


def test_admin_menu_shows_limit():
    markup = inline.admin_menu({"ping_limit": 64})
    assert "64" in buttons(markup)[0].text
    assert {b.callback_data for b in buttons(markup)} >= {"adm:limit", "adm:stats", "adm:bc"}


def test_confirm_and_cancel_keyboards():
    assert [b.callback_data for b in buttons(inline.confirm("yes:1", "no:1"))] == ["yes:1", "no:1"]
    assert buttons(inline.cancel_scan())[0].callback_data == "scan:cancel"
    assert buttons(inline.broadcast_cancel())[0].callback_data == "adm:bc:cancel"
    assert buttons(inline.back())[0].callback_data == "menu"
