"""Разбор цели сканирования. Только стандартная библиотека, без регулярок."""
from __future__ import annotations

import ipaddress


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


def subnet_label(ip: str) -> str:
    """192.168.0.0 -> 192.168.0.0/24 (подпись для истории и отчётов)."""
    return f"{ip.rsplit('.', 1)[0]}.0/24"
