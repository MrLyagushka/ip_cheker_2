"""Разбор целей сканирования и адресов серверов. Только стандартная библиотека."""
from __future__ import annotations

import ipaddress
import re

import config


def parse_target(text: str) -> tuple[list[str], str]:
    """Всегда возвращает СПИСОК адресов и тип: 'host' или 'subnet'.

    8.8.8.8      -> (['8.8.8.8'], 'host')
    192.168.0.0  -> (256 адресов, 'subnet')
    0.0.x.x      -> ValueError (такую сеть не сканируем)
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Пришли IPv4-адрес, например 8.8.8.8")
    try:
        ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        raise ValueError(f"«{text}» не похож на IPv4. Пример: 8.8.8.8 или 192.168.0.0") from None

    octets = [int(part) for part in text.split(".")]
    if octets[0] == 0 and octets[1] == 0:
        raise ValueError("Сеть 0.0.x.x сканировать нельзя")
    if octets[3] == 0:
        base = ".".join(str(part) for part in octets[:3])
        return [f"{base}.{i}" for i in range(256)], "subnet"
    return [text], "host"


def parse_single(text: str) -> str:
    """Для мониторинга: только одиночный IP, сети не принимаем."""
    ips, kind = parse_target(text)
    if kind != "host":
        raise ValueError("В мониторинг добавляется только одиночный IP, не сеть x.x.0")
    return ips[0]


def split_tokens(text: str) -> list[str]:
    """Адреса через пробел (запятая и ; тоже прощаются)."""
    return [token for token in re.split(r"[\s,;]+", (text or "").strip()) if token]


def parse_targets(text: str) -> tuple[list[str], str, str]:
    """Несколько целей за раз: '8.8.8.8 1.1.1.1 192.168.0.0'.

    Возвращает (адреса без дублей, тип, подпись для истории).
    Тип: 'host' — один адрес, 'subnet' — одна сеть, 'multi' — несколько целей.
    """
    tokens = split_tokens(text)
    if not tokens:
        raise ValueError("Пришли IPv4 через пробел, например: 8.8.8.8 1.1.1.1")

    addresses: list[str] = []
    seen: set[str] = set()
    labels: list[str] = []
    kinds: list[str] = []
    for token in tokens:
        ips, kind = parse_target(token)          # ошибка назовёт конкретный неверный токен
        kinds.append(kind)
        label = ips[0] if kind == "host" else subnet_label(ips[0])
        if label not in labels:
            labels.append(label)
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                addresses.append(ip)

    if len(addresses) > config.SCAN_MAX_IPS:
        raise ValueError(
            f"Слишком много адресов: {len(addresses)}. Лимит за один скан — {config.SCAN_MAX_IPS}"
        )
    if len(labels) == 1:
        return addresses, kinds[0], labels[0]
    label = ", ".join(labels)
    if len(label) > 120:
        label = label[:117] + "..."
    return addresses, "multi", label


def parse_host_port(text: str) -> tuple[str, int | None]:
    """Адрес сервера для прокси: '1.2.3.4' или '1.2.3.4:1080'."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Пришли IP сервера: 162.35.229.164 (можно с портом :1080)")
    host, _, port_text = raw.partition(":")
    host = parse_single(host)                    # сеть x.x.0 как адрес сервера не годится
    if not port_text:
        return host, None
    port = config.to_int(port_text, 0)
    if not 1 <= port <= 65535:
        raise ValueError(f"Порт «{port_text}» неверный. Нужно число 1…65535, например 1080")
    return host, port


def subnet_label(ip: str) -> str:
    """192.168.0.0 -> 192.168.0.0/24 (подпись для истории и отчётов)."""
    return f"{ip.rsplit('.', 1)[0]}.0/24"
