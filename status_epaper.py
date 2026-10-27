#!/usr/bin/env python3
"""Дублирует статус-страницу Uptime Kuma на трёхцветный e-paper WeAct 2.13":
имя каждого сервиса и столбики его проверок за последний час, недоступность — красным.

    python3 status_epaper.py [URL статус-страницы] [--preview файл.png]
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

from hello_epaper import EPD, FONT, HEIGHT, WIDTH

STATUS_PAGE = "http://10.0.0.16:3001/status/test"  # можно передать первым аргументом
SHOW_HEADER = True  # строка «название страницы · время обновления» сверху
WINDOW = timedelta(hours=1)  # за какой период рисовать столбики
BARS = 60  # столбиков в строке: при проверке раз в минуту — по столбику на минуту
BAR_W, BAR_GAP = 2, 1  # ширина столбика и промежутка между столбиками, px
TIMEOUT = 10  # таймаут запроса к Kuma, с

DOWN, UP, PENDING, MAINTENANCE = 0, 1, 2, 3  # коды status в Uptime Kuma
SEVERITY = {UP: 0, MAINTENANCE: 1, PENDING: 2, DOWN: 3}  # при склейке столбиков побеждает худший
UNAVAILABLE = (DOWN, PENDING)  # PENDING — проверка уже не прошла, Kuma перепроверяет


def get_json(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        return json.load(resp)


def parse_time(text):
    """Kuma отдаёт время проверок в UTC без зоны: "2026-10-26 23:33:58.290"."""
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def fetch(page_url):
    """Название страницы и [(имя сервиса, [статусы проверок за WINDOW от старых к новым])]."""
    url = urllib.parse.urlsplit(page_url)
    base = f"{url.scheme}://{url.netloc}"
    slug = url.path.rstrip("/").rsplit("/", 1)[-1]
    page = get_json(f"{base}/api/status-page/{slug}")
    heartbeats = get_json(f"{base}/api/status-page/heartbeat/{slug}")["heartbeatList"]  # до 100 последних
    beats = {mid: sorted((parse_time(b["time"]), b["status"]) for b in hbs) for mid, hbs in heartbeats.items()}
    # Kuma отдаёт снимок, который обновляется раз в минуту. Час отсчитываем от самой свежей проверки
    # в снимке, а не от часов платы: иначе у сервисов, проверенных после снимка, окно теряет столбик.
    end = max((b[-1][0] for b in beats.values() if b), default=datetime.now(timezone.utc))
    monitors = []
    for group in page["publicGroupList"]:
        for monitor in group["monitorList"]:
            recent = beats.get(str(monitor["id"]), [])
            monitors.append((monitor["name"], [status for t, status in recent if t > end - WINDOW]))
    return page["config"]["title"], monitors


def merge(statuses, n):
    """Не больше n столбиков: соседние проверки склеиваются, группа получает худший статус."""
    if len(statuses) <= n:
        return statuses
    size = len(statuses) / n
    return [max(statuses[int(i * size):int((i + 1) * size)], key=lambda s: SEVERITY.get(s, 0))
            for i in range(n)]


def fit(draw, text, font, width):
    """Обрезает текст с «…», чтобы он влез в width пикселей."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def blank():
    """Пустые слои в альбомной ориентации 250x122 и «перья» (рисовалка, цвет) для чёрного и красного."""
    black = Image.new("1", (HEIGHT, WIDTH), 255)  # ч/б слой: 1 = белый
    red = Image.new("1", (HEIGHT, WIDTH), 0)  # красный слой: 1 = красный
    return black, red, (ImageDraw.Draw(black), 0), (ImageDraw.Draw(red), 255)


def header(pen, title, now):
    """Строка «название · ЧЧ:ММ» с линией под ней. Возвращает её высоту."""
    draw, fill = pen
    font = ImageFont.truetype(FONT, 11)
    draw.text((2, 0), title, font=font, fill=fill)
    draw.text((HEIGHT - 2, 0), now.astimezone().strftime("%H:%M"), font=font, fill=fill, anchor="ra")
    draw.line([0, 13, HEIGHT - 1, 13], fill=fill)
    return 14


def render_status(title, monitors, now):
    """Чёрный и красный слои 122x250: по строке на сервис — имя и столбики проверок, новые справа."""
    black, red, ink, red_ink = blank()
    draw = ink[0]
    top = header(ink, title, now) if SHOW_HEADER else 0
    row_h = (WIDTH - top) / max(len(monitors), 1)
    font = ImageFont.truetype(FONT, min(14, int(row_h) - 4))
    bars_x = HEIGHT - 2 - BARS * (BAR_W + BAR_GAP) + BAR_GAP  # столбики прижаты к правому краю
    name_w = min(bars_x - 8, max((draw.textlength(name, font=font) for name, _ in monitors), default=0))

    for i, (name, statuses) in enumerate(monitors):
        y0, y1 = round(top + i * row_h + 2), round(top + (i + 1) * row_h - 3)
        pen = red_ink if statuses and statuses[-1] in UNAVAILABLE else ink  # сейчас недоступен — имя красное
        pen[0].text((2, (y0 + y1) / 2), fit(draw, name, font, name_w), font=font, fill=pen[1], anchor="lm")

        bars = merge(statuses, BARS)
        x = HEIGHT - 2 - len(bars) * (BAR_W + BAR_GAP) + BAR_GAP
        for status in bars:
            bar_draw, fill = red_ink if status in UNAVAILABLE else ink
            bar_top = (y0 + y1) // 2 if status == MAINTENANCE else y0
            bar_draw.rectangle([x, bar_top, x + BAR_W - 1, y1], fill=fill)
            x += BAR_W + BAR_GAP

    return black.rotate(90, expand=True), red.rotate(90, expand=True)  # в родную ориентацию 122x250


def render_error(error, now):
    """Экран вместо столбиков, когда Kuma не ответила: старые столбики не должны выглядеть свежими."""
    black, red, ink, red_ink = blank()
    big, small = ImageFont.truetype(FONT, 22), ImageFont.truetype(FONT, 11)
    reason = str(getattr(error, "reason", error))
    for pen, text, font, y in ((red_ink, "Мониторинг", big, 26), (red_ink, "недоступен", big, 52),
                               (ink, fit(ink[0], reason, small, HEIGHT - 8), small, 82),
                               (ink, now.astimezone().strftime("%H:%M"), small, 102)):
        pen[0].text((HEIGHT // 2, y), text, font=font, fill=pen[1], anchor="mm")
    return black.rotate(90, expand=True), red.rotate(90, expand=True)


def save_preview(black, red, path):
    """RGB-картинка того, что будет на экране, в альбомной ориентации."""
    image = black.convert("RGB")
    image.paste((200, 0, 0), mask=red)
    image.rotate(-90, expand=True).save(path)


def main():
    parser = argparse.ArgumentParser(description="Статус-страница Uptime Kuma на e-paper.")
    parser.add_argument("url", nargs="?", default=STATUS_PAGE, help=f"статус-страница (по умолчанию {STATUS_PAGE})")
    parser.add_argument("--preview", metavar="PNG", help="сохранить картинку в файл, дисплей не трогать")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    try:
        title, monitors = fetch(args.url)
    except (OSError, ValueError, KeyError) as error:  # сеть, HTTP, битый JSON
        print(f"Kuma не ответила: {error}", file=sys.stderr)
        layers = render_error(error, now)
    else:
        layers = render_status(title, monitors, now)

    if args.preview:
        save_preview(*layers, args.preview)
        return
    epd = EPD()
    try:
        epd.init()
        epd.display(*layers)
        epd.sleep()
    finally:
        epd.close()


if __name__ == "__main__":
    main()
