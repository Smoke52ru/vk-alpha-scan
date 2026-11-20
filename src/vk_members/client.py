import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests

API_URL = "https://api.vk.com/method/groups.getMembers"
PAGE_SIZE = 1000
# Любое непустое fields переключает ответ со списка id на объекты
# пользователя. Имя и фамилия приходят как базовые поля.
FIELDS = "domain"
RETRYABLE_CODES = {6, 9, 10}
MAX_ATTEMPTS = 5


class VkApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"VK API {code}: {message}")


@dataclass(frozen=True)
class Page:
    users: list[dict[str, Any]]
    total: int
    received: int
    incomplete: bool


def iter_pages(
    session: requests.Session,
    *,
    token: str,
    group_id: str,
    version: str,
    delay: float,
) -> Iterator[Page]:
    offset = 0
    total: int | None = None
    seen: set[int] = set()

    while total is None or offset < total:
        data = _get_page(
            session,
            token=token,
            group_id=group_id,
            version=version,
            offset=offset,
            delay=delay,
        )
        page_total = data.get("count")
        items = data.get("items")
        if not isinstance(page_total, int) or not isinstance(items, list):
            raise VkApiError(0, "неожиданный формат ответа")
        total = page_total

        if not items:
            yield Page(
                users=[],
                total=total,
                received=offset,
                incomplete=offset < total,
            )
            return
        if not any(isinstance(item, dict) for item in items):
            raise VkApiError(0, "API вернуло список id без имён. Проверьте версию API.")

        fresh: list[dict[str, Any]] = []
        for item in items:
            user = _as_user(item)
            if user is None:
                continue
            user_id = user["id"]
            if user_id in seen:
                continue
            seen.add(user_id)
            fresh.append(user)

        offset += len(items)
        yield Page(
            users=fresh,
            total=total,
            received=offset,
            incomplete=False,
        )
        if offset < total:
            time.sleep(delay)


def _as_user(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    user_id = item.get("id")
    if not isinstance(user_id, int):
        return None
    return item


def _get_page(
    session: requests.Session,
    *,
    token: str,
    group_id: str,
    version: str,
    offset: int,
    delay: float,
) -> dict[str, Any]:
    attempt = 0
    while True:
        attempt += 1
        try:
            response = session.get(
                API_URL,
                params={
                    "group_id": group_id,
                    "sort": "id_asc",
                    "offset": offset,
                    "count": PAGE_SIZE,
                    "fields": FIELDS,
                    "v": version,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt >= MAX_ATTEMPTS:
                raise VkApiError(0, str(exc)) from exc
            time.sleep(_backoff(attempt, delay))
            continue

        if not isinstance(payload, dict):
            raise VkApiError(0, "неожиданный формат ответа")

        error = payload.get("error")
        if error is not None:
            code, message = _error_parts(error)
            if code in RETRYABLE_CODES and attempt < MAX_ATTEMPTS:
                time.sleep(_backoff(attempt, delay))
                continue
            raise VkApiError(code, message)

        data = payload.get("response")
        if not isinstance(data, dict):
            raise VkApiError(0, "неожиданный формат ответа")
        return data


def _error_parts(error: object) -> tuple[int, str]:
    if isinstance(error, dict):
        code = error.get("error_code", 0)
        message = error.get("error_msg", "неизвестная ошибка")
        if isinstance(code, int) and isinstance(message, str):
            return code, message
    return 0, "неизвестная ошибка"


def _backoff(attempt: int, delay: float) -> float:
    return max(delay, 1.0) * (2 ** (attempt - 1))
