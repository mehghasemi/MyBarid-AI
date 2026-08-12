"""انتزاع Provider هوش مصنوعی. عمداً فقط از urllib استاندارد پایتون استفاده
می‌شود تا هیچ پکیج شبکه‌ای اضافه (مثل requests) لازم نباشد.

افزودن Provider جدید: یک کلاس با متد complete(...) بنویسید و در
get_provider ثبت کنید. هیچ بخش دیگری از برنامه به نوع Provider وابسته نیست.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class AIProviderError(Exception):
    """خطای قابل‌نمایش (پیام فارسی) هنگام فراخوانی Provider."""


@dataclass
class AISettings:
    provider: str = "openai"  # openai | custom | gemini | disabled
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"  # برای custom/OpenAI-Compatible قابل تغییر
    temperature: float = 0.2
    max_tokens: int = 1200
    batch_size: int = 5
    enabled: bool = False


class BaseProvider:
    def complete(self, system: str, user: str, settings: AISettings) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    """برای OpenAI رسمی و هر API سازگار با OpenAI (Custom Endpoint / برخی مدل‌های Local مثل Ollama با
    OpenAI-compatible server یا LM Studio)."""

    def complete(self, system: str, user: str, settings: AISettings) -> str:
        url = settings.base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps({
            "model": settings.model,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise AIProviderError(f"خطای سرویس AI ({exc.code}): {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(f"عدم دسترسی به سرویس AI: {exc.reason}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIProviderError("پاسخ سرویس AI ساختار مورد انتظار را نداشت.") from exc


class GeminiProvider(BaseProvider):
    def complete(self, system: str, user: str, settings: AISettings) -> str:
        model = settings.model or "gemini-1.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={settings.api_key}"
        )
        payload = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": settings.temperature,
                "maxOutputTokens": settings.max_tokens,
                "responseMimeType": "application/json",
            },
        }).encode("utf-8")
        request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise AIProviderError(f"خطای سرویس Gemini ({exc.code}): {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise AIProviderError(f"عدم دسترسی به سرویس Gemini: {exc.reason}") from exc
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise AIProviderError("پاسخ سرویس Gemini ساختار مورد انتظار را نداشت.") from exc


def get_provider(settings: AISettings) -> BaseProvider:
    if settings.provider in ("openai", "custom"):
        return OpenAICompatibleProvider()
    if settings.provider == "gemini":
        return GeminiProvider()
    raise AIProviderError(f"Provider «{settings.provider}» پشتیبانی نمی‌شود.")
