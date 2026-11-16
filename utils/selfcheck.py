"""Самопроверка окружения: ICMP и связь с Telegram (в том числе через прокси).

Запуск внутри контейнера:
    docker compose exec bot python -m utils.selfcheck

Смысл: в Docker бот может «успешно» пинговать и получать для всех адресов
«недоступен» — это не падение, а тихая ложь. Поэтому окружение проверяем явно.
"""
from __future__ import annotations

import asyncio
import shutil

from aiogram.exceptions import TelegramUnauthorizedError

import config
from utils import ping, storage, text

ICMP_HINT = (
    "ICMP в контейнере не работает. Проверь по порядку:\n"
    '  1) в образе установлен iputils-ping (apt install iputils-ping);\n'
    '  2) в docker-compose.yml есть sysctls: net.ipv4.ping_group_range: "0 2147483647";\n'
    "  3) если включён no-new-privileges или cap_drop: NET_RAW — file-capability у ping\n"
    "     не сработает: оставь sysctl из п.2 либо cap_add: [NET_RAW] и user: root;\n"
    "  4) обходной путь на Linux: network_mode: host."
)

PROXY_HINT = (
    "Не удалось связаться с Telegram. Если используется прокси, проверь:\n"
    "  1) 127.0.0.1/localhost внутри контейнера — это сам контейнер, а не хост.\n"
    "     Замени на host.docker.internal (compose пробрасывает host-gateway),\n"
    "     на IP хоста в docker-сети или на имя сервиса прокси в той же сети;\n"
    "  2) прокси должен слушать не только loopback (0.0.0.0 или адрес docker-моста)\n"
    "     и пускать клиентов из подсети контейнеров (обычно 172.16.0.0/12);\n"
    "  3) схема socks5:// — aiogram сам резолвит DNS через прокси (rdns=True);\n"
    "     socks5h:// НЕ поддерживается aiohttp-socks и уронит бота;\n"
    "  4) HTTP_PROXY/HTTPS_PROXY/ALL_PROXY aiogram игнорирует (сессия без trust_env):\n"
    "     работает только PROXY_URL из .env или proxy из админ-панели;\n"
    "  5) ping через прокси не ходит и от прокси не зависит."
)


async def check_ping() -> tuple[bool, str]:
    """Пингуем loopback: это проверяет права и наличие ping, а не сеть."""
    if shutil.which("ping") is None:
        return False, "Команда ping не найдена.\n" + ICMP_HINT
    try:
        proc = await asyncio.create_subprocess_exec(
            *ping.build_cmd("127.0.0.1"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception as exc:
        return False, f"ping не запустился: {exc}\n{ICMP_HINT}"

    body = (out or b"").decode("utf-8", "replace").strip()
    code = proc.returncode
    if code == 0:
        return True, "ICMP работает (ping 127.0.0.1 прошёл)"
    # Код 1 = «адрес не ответил», код 2+ = ошибка самого ping (права, аргументы, DNS).
    if code >= 2 or "not permitted" in body.lower() or "capability" in body.lower():
        return False, f"ping вернул код {code}: {body[:200]}\n{ICMP_HINT}"
    return False, f"ping 127.0.0.1 не ответил: {body[:200]}"


async def check_telegram(bot) -> tuple[bool, str]:
    """get_me через ту же сессию (и тот же прокси), что и весь бот."""
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=20)
    except TelegramUnauthorizedError as exc:
        # Сеть и прокси тут ни при чём: сервер ответил, но токен не принят.
        return False, (
            f"Токен не принят: {exc}\n"
            "Проверь TOKEN в .env: он должен быть целиком, без пробелов и кавычек,\n"
            "и не отозван через @BotFather. Прокси в этом случае ни при чём."
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}\n{PROXY_HINT}"
    proxy = text.mask_proxy(storage.load_settings().get("proxy") or config.PROXY_URL)
    return True, f"Telegram доступен: @{me.username} (прокси: {proxy})"


async def run(bot=None) -> bool:
    ok_ping, ping_detail = await check_ping()
    print(f"[ping] {'OK' if ok_ping else 'ОШИБКА'}: {ping_detail}")
    if bot is None:
        print("[telegram] ПРОПУСК: TOKEN не задан")
        return ok_ping
    ok_telegram, telegram_detail = await check_telegram(bot)
    print(f"[telegram] {'OK' if ok_telegram else 'ОШИБКА'}: {telegram_detail}")
    return ok_ping and ok_telegram


def main() -> None:
    from main import build_bot  # локальный импорт: main импортирует нас при старте

    bot = build_bot() if config.TOKEN else None

    async def scenario() -> bool:
        try:
            return await run(bot)
        finally:
            if bot is not None:
                await bot.session.close()

    raise SystemExit(0 if asyncio.run(scenario()) else 1)


if __name__ == "__main__":
    main()
