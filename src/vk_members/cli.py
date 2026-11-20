import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from vk_members.client import Page, VkApiError, iter_pages
from vk_members.filter import parse_letters, surname_matches

CSV_COLUMNS = ("id", "first_name", "last_name", "domain", "url")
DEFAULT_DELAY = 0.35
DEFAULT_VERSION = "5.199"
DEFAULT_OUTPUT = "members.csv"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    token: str
    group_id: str
    letters: frozenset[str]
    output: Path
    api_version: str
    delay: float
    keep_yo: bool


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    try:
        settings = _settings(_parser().parse_args(argv))
        written = _export(settings)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except VkApiError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(
        f"Готово: записано {written} в {settings.output}",
        file=sys.stderr,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Сохраняет участников сообщества ВКонтакте, "
            "чья фамилия начинается на заданные буквы."
        ),
    )
    parser.add_argument(
        "--group",
        default=os.environ.get("VK_GROUP_ID"),
        help="Короткое имя или id сообщества. По умолчанию VK_GROUP_ID.",
    )
    parser.add_argument(
        "--letters",
        default=os.environ.get("VK_LETTERS"),
        help='Буквы фамилии, например "А,К,М". По умолчанию VK_LETTERS.',
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("VK_OUTPUT", DEFAULT_OUTPUT),
        help=f"CSV-файл. По умолчанию {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help=(
            "Пауза между запросами в секундах. "
            "По умолчанию VK_REQUEST_DELAY или 0.35."
        ),
    )
    parser.add_argument(
        "--keep-yo",
        action="store_true",
        help="Не считать «ё» и «е» одной буквой.",
    )
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    token = os.environ.get("VK_TOKEN", "").strip()
    if not token:
        raise ConfigError("Укажите VK_TOKEN в файле .env.")

    group_id = (args.group or "").strip()
    if not group_id:
        raise ConfigError("Укажите сообщество: --group или VK_GROUP_ID.")

    raw_letters = (args.letters or "").strip()
    if not raw_letters:
        raise ConfigError("Укажите буквы фамилии: --letters или VK_LETTERS.")
    letters = parse_letters(raw_letters, keep_yo=args.keep_yo)
    if not letters:
        raise ConfigError("В списке букв нет ни одной буквы.")

    output = Path(args.output)
    if output.exists() and output.is_dir():
        raise ConfigError(f"Путь вывода указывает на каталог: {output}")

    version = os.environ.get("VK_API_VERSION", DEFAULT_VERSION).strip() or DEFAULT_VERSION
    delay = _delay(args.delay)
    return Settings(
        token=token,
        group_id=group_id,
        letters=letters,
        output=output,
        api_version=version,
        delay=delay,
        keep_yo=args.keep_yo,
    )


def _delay(explicit: float | None) -> float:
    if explicit is not None:
        value = explicit
    else:
        raw = os.environ.get("VK_REQUEST_DELAY", str(DEFAULT_DELAY)).strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ConfigError("Пауза между запросами должна быть неотрицательным числом.") from exc
    if not math.isfinite(value) or value < 0:
        raise ConfigError("Пауза между запросами должна быть неотрицательным числом.")
    return value


def _export(settings: Settings) -> int:
    settings.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with requests.Session() as session, settings.output.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for page in iter_pages(
            session,
            token=settings.token,
            group_id=settings.group_id,
            version=settings.api_version,
            delay=settings.delay,
        ):
            for user in page.users:
                if _matches(user, settings):
                    writer.writerow(_row(user))
                    written += 1
            _report(page, written)
            if page.incomplete:
                print(
                    "API вернуло пустую страницу раньше конца списка. Останавливаюсь.",
                    file=sys.stderr,
                )
                break
    return written


def _matches(user: dict[str, Any], settings: Settings) -> bool:
    if user.get("deactivated"):
        return False
    last_name = user.get("last_name")
    if not isinstance(last_name, str):
        return False
    return surname_matches(last_name, settings.letters, keep_yo=settings.keep_yo)


def _row(user: dict[str, Any]) -> dict[str, str]:
    user_id = user["id"]
    domain = user.get("domain")
    screen_name = domain if isinstance(domain, str) else ""
    return {
        "id": str(user_id),
        "first_name": _text(user.get("first_name")),
        "last_name": _text(user.get("last_name")),
        "domain": screen_name,
        "url": f"https://vk.com/id{user_id}",
    }


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _report(page: Page, written: int) -> None:
    print(
        f"получено {page.received} из {page.total}, подошло {written}",
        file=sys.stderr,
    )
