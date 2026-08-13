"""نقطه ورود اپلیکیشن ارزیابی کیفیت CRM.

اجرا: python main.py  (یا دابل‌کلیک روی run.cmd در ویندوز)
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

import webview  # noqa: E402

from bridge import Api  # noqa: E402
from database import db  # noqa: E402

WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"


def get_app_version() -> str:
    version_file = APP_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _show_fatal_error(title: str, message: str) -> None:
    """پیام خطا را هم در کنسول چاپ می‌کند و هم (روی ویندوز) به‌صورت یک
    پنجره پیام Native نشان می‌دهد، چون ممکن است کاربر بلافاصله بعد از
    بسته‌شدن پنجره برنامه، کنسول را هم ببندد."""
    print("\n" + "=" * 60)
    print(title)
    print(message)
    print("=" * 60 + "\n")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
        except Exception:  # noqa: BLE001
            pass


def main():
    db.init_db()
    api = Api()
    index_path = APP_ROOT / "ui" / "index.html"

    window = webview.create_window(
        f"ارزیابی کیفیت عملکرد کارشناسان CRM - نسخه {get_app_version()}",
        str(index_path),
        js_api=api,
        width=1440,
        height=900,
        min_size=(1100, 700),
        text_select=True,
    )
    api.set_window(window)

    # روی ویندوز، موتور نمایش را صراحتاً EdgeChromium (WebView2) درخواست می‌کنیم.
    # اگر این موتور روی سیستم موجود نباشد، pywebview به‌صورت خاموش سراغ یک موتور
    # قدیمی (MSHTML/IE) می‌رود که جاوااسکریپت مدرن این اپلیکیشن را اجرا نمی‌کند
    # و باعث می‌شود کل رابط کاربری (دکمه‌ها، معیارها، ...) بدون هیچ خطای واضحی
    # از کار بیفتد. به همین دلیل، به‌جای اجازه‌دادن به این Fallback خاموش،
    # خطا را می‌گیریم و به کاربر راهنمایی روشن می‌دهیم.
    gui_backend = "edgechromium" if sys.platform == "win32" else None
    try:
        webview.start(gui=gui_backend, debug="--debug" in sys.argv)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _show_fatal_error(
            "خطا در راه‌اندازی موتور نمایش (WebView2)",
            "برنامه نتوانست موتور نمایش Microsoft Edge WebView2 را راه‌اندازی کند.\n\n"
            "این موتور روی اغلب سیستم‌های ویندوز ۱۰/۱۱ از قبل نصب است، اما به نظر می‌رسد "
            "روی این سیستم موجود نیست یا نسخه آن قدیمی است.\n\n"
            "لطفاً یکی از راه‌های زیر را امتحان کنید:\n"
            "۱. اگر اینترنت دارید: از این آدرس Evergreen Bootstrapper را نصب کنید:\n"
            f"   {WEBVIEW2_DOWNLOAD_URL}\n"
            "۲. اگر اینترنت شرکتی محدود است: عبارت «WebView2 Runtime Standalone "
            "Installer» را جستجو و نسخه آفلاین کامل را از سایت microsoft.com دانلود/نصب کنید.\n"
            "۳. بعد از نصب، کامپیوتر را Restart کرده و دوباره run.cmd را اجرا کنید.\n"
            "۴. اگر مشکل ادامه داشت: روی run.cmd راست‌کلیک کرده و «Run as administrator» را "
            "بزنید. حتی کاربرانی که عضو گروه Administrator هستند، به‌طور پیش‌فرض با دسترسی "
            "محدود اجرا می‌شوند مگر صریحاً درخواست Elevation شود؛ این موضوع می‌تواند باعث "
            "هنگ‌کردن یا کرش برنامه هنگام راه‌اندازی WebView2 شود (run.cmd از نگارش فعلی خودش "
            "این کار را خودکار انجام می‌دهد، اما در برخی سیستم‌های محدودشده شرکتی ممکن است "
            "نیاز به تأیید دستی هم باشد).\n\n"
            f"جزئیات فنی خطا:\n{exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
