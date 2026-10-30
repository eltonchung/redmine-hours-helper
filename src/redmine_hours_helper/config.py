"""Validated, non-secret configuration. API keys are never serialized."""

import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """A user-editable setting is missing or invalid."""


def positive_id(value: object, label: str) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(str(value)) < 1:
        raise ConfigError(f"{label} 必須是正整數 / must be a positive integer.")
    return int(str(value))


def hours_value(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ConfigError("工時必須是數字 / Hours must be numeric.") from None
    if not result.is_finite() or result < 0:
        raise ConfigError("工時必須是非負有限數值 / Hours must be finite and non-negative.")
    return result


@dataclass(frozen=True)
class Settings:
    redmine_url: str
    issue_id: int
    activity_id: int
    daily_hours: Decimal = Decimal("8")
    comment: str = ""
    holidays_file: str = ""
    timeout_seconds: float = 20

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        if not isinstance(data, dict):
            raise ConfigError("設定必須是 JSON 物件 / Configuration must be a JSON object.")
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(
                "設定含不支援的欄位；API Key 請使用環境變數 / Unsupported configuration fields; use the environment for API keys."
            )
        url = data.get("redmine_url", "")
        if not isinstance(url, str):
            raise ConfigError("Redmine URL 必須是文字 / must be text.")
        url = url.strip().rstrip("/")
        try:
            parts = urlsplit(url)
            valid = (
                parts.scheme == "https"
                and parts.hostname
                and parts.port != 0
                and not parts.username
                and not parts.password
                and not parts.query
                and not parts.fragment
                and not any(c.isspace() or ord(c) < 32 for c in url)
                and "\\" not in url
            )
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError(
                "請使用 HTTPS 基底網址，不含帳密、查詢參數或片段 / Use an HTTPS base URL without credentials, query or fragment."
            )
        hours = hours_value(data.get("daily_hours", 8))
        if not Decimal("0") < hours <= 24 or hours.as_tuple().exponent < -2:
            raise ConfigError(
                "每日工時須大於 0、最多 24，且最多兩位小數 / Daily hours must be > 0, ≤ 24, with at most two decimal places."
            )
        comment = data.get("comment", "")
        calendar = data.get("holidays_file", "")
        if not isinstance(comment, str) or len(comment) > 255:
            raise ConfigError("備註最多 255 字元 / Comment must be text, at most 255 characters.")
        if not isinstance(calendar, str):
            raise ConfigError("行事曆路徑必須是文字 / Calendar path must be text.")
        try:
            timeout = float(data.get("timeout_seconds", 20))
        except (ValueError, TypeError):
            timeout = 0
        if isinstance(data.get("timeout_seconds"), bool) or not 1 <= timeout <= 120:
            raise ConfigError(
                "逾時秒數須介於 1 至 120 / Timeout must be between 1 and 120 seconds."
            )
        return cls(
            url,
            positive_id(data.get("issue_id"), "Issue ID"),
            positive_id(data.get("activity_id"), "Activity ID"),
            hours,
            comment,
            calendar,
            timeout,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["daily_hours"] = str(self.daily_hours)
        return data


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError(
            "無法讀取設定 JSON；請由 config.example.json 建立 / Cannot read configuration JSON; copy config.example.json first."
        ) from None
    return Settings.from_dict(data)


def save_settings(settings: Settings, path: Path) -> None:
    """Save only non-secret fields. The GUI deliberately requires a *.local.json path."""
    path.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def validate_api_key(value: str) -> str:
    key = value.strip()
    if not key or not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key):
        raise ConfigError(
            "請輸入有效 API Key 或設定 REDMINE_API_KEY / Enter a valid API key or set REDMINE_API_KEY."
        )
    return key
