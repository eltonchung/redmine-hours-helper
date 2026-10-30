"""Small Redmine client with complete reads and conservative writes."""

import datetime as dt
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

import requests

from .config import ConfigError, Settings, hours_value, positive_id, validate_api_key


class RedmineError(RuntimeError):
    """A read failed, or a write was explicitly rejected."""


class WriteUncertainError(RedmineError):
    """A write may have succeeded. Stop and reconcile before another attempt."""


class RedmineClient:
    def __init__(self, settings: Settings, api_key: str, session=None):
        self.settings = settings
        self._session = session if session is not None else requests.Session()
        self._headers = {
            "X-Redmine-API-Key": validate_api_key(api_key),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._user_id: int | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._session.close()

    def _request(self, method: str, resource: str, **kwargs):
        url = self.settings.redmine_url + "/" + resource
        for hop in range(4):
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._headers,
                    allow_redirects=False,
                    timeout=(min(5, self.settings.timeout_seconds), self.settings.timeout_seconds),
                    **kwargs,
                )
            except requests.RequestException:
                if method == "POST":
                    raise WriteUncertainError(
                        "送出結果不明，請到 Redmine 核對後重新預覽 / Write outcome unknown; check Redmine, then preview again."
                    ) from None
                raise RedmineError(
                    "連線失敗或逾時，未將工時視為零 / Connection failed or timed out; hours are unknown."
                ) from None
            if response.status_code in (301, 302, 303, 307, 308):
                if method == "POST":
                    raise WriteUncertainError(
                        "寫入遇到重新導向，未重送；請核對紀錄並使用最終 HTTPS 網址 / Write redirected; not resent. Check entries and use the final HTTPS URL."
                    )
                location = response.headers.get("Location", "")
                target = urljoin(url, location)
                try:
                    old, new = urlsplit(url), urlsplit(target)
                    safe = (
                        bool(location)
                        and new.scheme == "https"
                        and (old.hostname, old.port or 443) == (new.hostname, new.port or 443)
                        and not new.username
                        and not new.password
                        and not new.query
                        and not new.fragment
                        and not any(c.isspace() or ord(c) < 32 for c in target)
                        and "\\" not in target
                    )
                except ValueError:
                    safe = False
                if not safe or hop == 3:
                    raise RedmineError(
                        "已阻止不安全或過多的重新導向 / Unsafe or excessive redirect blocked; check the base URL."
                    )
                url = target
                continue
            if method == "POST" and (response.status_code >= 500 or response.status_code == 408):
                raise WriteUncertainError(
                    "伺服器未確認寫入，請先核對 Redmine / Server did not confirm the write; check Redmine first."
                )
            if response.status_code not in ((200,) if method == "GET" else (200, 201)):
                raise RedmineError(
                    f"Redmine HTTP {response.status_code}；請檢查權限與設定 / Check permissions and settings."
                )
            return response
        raise RedmineError("重新導向過多 / Too many redirects.")

    @staticmethod
    def _json(response) -> dict:
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError
            return body
        except ValueError:
            raise RedmineError(
                "Redmine 回應不是預期的 JSON 物件 / Unexpected JSON response."
            ) from None

    def current_user_id(self) -> int:
        if self._user_id is None:
            body = self._json(self._request("GET", "users/current.json"))
            try:
                self._user_id = positive_id(body["user"]["id"], "User ID")
            except (KeyError, TypeError, ConfigError):
                raise RedmineError("無法確認 API 使用者 / Cannot verify the API user.") from None
        return self._user_id

    def hours_for_day(self, day: dt.date) -> Decimal:
        """Count all issues for the authenticated user; reject incomplete/mismatched data."""
        user_id = self.current_user_id()
        total = Decimal("0")
        offset = 0
        expected_count = None
        seen: set[int] = set()
        while True:
            body = self._json(
                self._request(
                    "GET",
                    "time_entries.json",
                    params={
                        "user_id": user_id,
                        "spent_on": day.isoformat(),
                        "offset": offset,
                        "limit": 100,
                    },
                )
            )
            try:
                entries, count, returned_offset = (
                    body["time_entries"],
                    body["total_count"],
                    body["offset"],
                )
                if (
                    not isinstance(entries, list)
                    or type(count) is not int
                    or count < 0
                    or count > 10000
                    or type(returned_offset) is not int
                    or returned_offset != offset
                    or (expected_count is not None and count != expected_count)
                ):
                    raise ValueError
                expected_count = count
                for entry in entries:
                    entry_id = positive_id(entry["id"], "Entry ID")
                    if (
                        entry_id in seen
                        or entry["spent_on"] != day.isoformat()
                        or entry["user"]["id"] != user_id
                    ):
                        raise ValueError
                    seen.add(entry_id)
                    total += hours_value(entry["hours"])
                offset += len(entries)
                if offset > count or (offset < count and not entries):
                    raise ValueError
                if offset == count:
                    return total
            except (KeyError, TypeError, ValueError):
                raise RedmineError(
                    "工時資料不完整、已變動或不符合查詢條件，停止計算 / Incomplete, changed or mismatched time entries; calculation stopped."
                ) from None

    def create_entry(self, day: dt.date, hours: Decimal) -> int:
        user_id = self.current_user_id()
        if not hours.is_finite() or not 0 < hours <= self.settings.daily_hours:
            raise RedmineError("待補工時無效 / Invalid hours to add.")
        response = self._request(
            "POST",
            "time_entries.json",
            json={
                "time_entry": {
                    "issue_id": self.settings.issue_id,
                    "activity_id": self.settings.activity_id,
                    "spent_on": day.isoformat(),
                    "hours": float(hours),
                    "comments": self.settings.comment,
                }
            },
        )
        try:
            entry = self._json(response)["time_entry"]
            entry_id = positive_id(entry["id"], "Entry ID")
            if (
                entry["spent_on"] != day.isoformat()
                or hours_value(entry["hours"]) != hours
                or entry["issue"]["id"] != self.settings.issue_id
                or entry["activity"]["id"] != self.settings.activity_id
                or entry["user"]["id"] != user_id
            ):
                raise ValueError
            return entry_id
        except (RedmineError, KeyError, TypeError, ValueError):
            raise WriteUncertainError(
                "未取得可驗證的新增紀錄；請核對 Redmine，勿直接重送 / Created entry could not be verified; check Redmine before retrying."
            ) from None
