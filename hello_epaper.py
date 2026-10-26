#!/usr/bin/env python3
"""Выводит текст (по умолчанию "Hello World") в красной рамке на трёхцветный e-paper
WeAct 2.13" (SSD1680, 122x250), подключённый к Orange Pi Zero 3.

    python3 hello_epaper.py ["любой текст"]
"""

import glob
import sys
import time

import gpiod
import spidev
from gpiod.line import Direction, Value
from PIL import Image, ImageDraw, ImageFont

# Смещение линии в 300b000.pinctrl = номер банка * 32 + номер пина (PC — банк 2)
RST_PIN = 70   # физ. пин 11, PC6
BUSY_PIN = 69  # физ. пин 13, PC5
DC_PIN = 71    # физ. пин 22, PC7
GPIO_CHIP_LABEL = "300b000.pinctrl"
SPI_BUS, SPI_DEV = 1, 1  # /dev/spidev1.1: MOSI пин 19, CLK пин 23, CS пин 24 (PH9 = аппаратный CS1)

WIDTH, HEIGHT = 122, 250  # родная (портретная) ориентация панели
REFRESH_TIME = 30  # по замеру BUSY полное обновление трёхцветной панели идёт 20–30 с
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def find_gpiochip(label):
    for path in sorted(glob.glob("/dev/gpiochip*")):
        with gpiod.Chip(path) as chip:
            if chip.get_info().label == label:
                return path
    raise RuntimeError(f"gpiochip с меткой {label} не найден")


class EPD:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEV)
        self.spi.max_speed_hz = 4_000_000
        self.spi.mode = 0
        self.gpio = gpiod.request_lines(
            find_gpiochip(GPIO_CHIP_LABEL),
            consumer="epaper",
            config={
                (RST_PIN, DC_PIN): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
                BUSY_PIN: gpiod.LineSettings(direction=Direction.INPUT),
            },
        )

    def close(self):
        self.gpio.release()
        self.spi.close()

    def command(self, cmd, *data):
        self.gpio.set_value(DC_PIN, Value.INACTIVE)
        self.spi.writebytes2([cmd])
        if data:
            self.data(data)

    def data(self, buf):
        self.gpio.set_value(DC_PIN, Value.ACTIVE)
        self.spi.writebytes2(buf)

    def busy(self):
        return self.gpio.get_value(BUSY_PIN) == Value.ACTIVE

    def wait_busy(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.busy():
            if time.monotonic() > deadline:
                raise TimeoutError("BUSY не опустился — проверьте подключение BUSY/RST/питания")
            time.sleep(0.01)

    def reset(self):
        for value, delay in ((Value.ACTIVE, 0.02), (Value.INACTIVE, 0.002), (Value.ACTIVE, 0.02)):
            self.gpio.set_value(RST_PIN, value)
            time.sleep(delay)

    def init(self):
        self.reset()
        self.wait_busy()
        self.command(0x12)  # программный сброс
        time.sleep(0.01)
        self.wait_busy()
        self.command(0x01, (HEIGHT - 1) & 0xFF, (HEIGHT - 1) >> 8, 0x00)  # 250 строк (gate)
        self.command(0x11, 0x03)  # заполнение RAM: X+, затем Y+
        self.command(0x44, 0x00, (WIDTH - 1) // 8)  # окно RAM по X: байты 0..15
        self.command(0x45, 0x00, 0x00, (HEIGHT - 1) & 0xFF, (HEIGHT - 1) >> 8)  # по Y: 0..249
        self.command(0x3C, 0x05)  # рамка
        self.command(0x21, 0x00, 0x80)  # обе RAM без инверсии
        self.command(0x18, 0x80)  # встроенный датчик температуры
        self.wait_busy()

    def display(self, black, red):
        # PIL в режиме "1" пакует строки по 16 байт — ровно формат RAM SSD1680.
        # Ч/б RAM (0x24): 1 = белый, 0 = чёрный. Красная RAM (0x26): 1 = красный.
        for ram, image in ((0x24, black), (0x26, red)):
            self.command(0x4E, 0x00)  # курсор RAM X
            self.command(0x4F, 0x00, 0x00)  # курсор RAM Y
            self.command(ram)
            self.data(image.tobytes())
        self.command(0x22, 0xF7)  # полное обновление
        self.command(0x20)
        time.sleep(0.1)
        if self.busy():
            self.wait_busy(REFRESH_TIME + 10)
        else:
            print(f"BUSY не поднялся — жду {REFRESH_TIME} с вслепую (проверьте провод BUSY, пин 13)",
                  file=sys.stderr)
            time.sleep(REFRESH_TIME)

    def sleep(self):
        self.command(0x10, 0x01)  # глубокий сон: картинка остаётся, ток почти нулевой


def render(text):
    """Чёрный и красный слои 122x250: текст по центру и красная рамка по краю."""
    black = Image.new("1", (HEIGHT, WIDTH), 255)  # рисуем в альбомной ориентации 250x122
    draw = ImageDraw.Draw(black)
    size = 48
    font = ImageFont.truetype(FONT, size)
    while size > 10 and draw.textlength(text, font=font) > HEIGHT - 16:
        size -= 2
        font = ImageFont.truetype(FONT, size)
    draw.text((HEIGHT // 2, WIDTH // 2), text, font=font, fill=0, anchor="mm")

    red = Image.new("1", (HEIGHT, WIDTH), 0)
    ImageDraw.Draw(red).rectangle([0, 0, HEIGHT - 1, WIDTH - 1], outline=255, width=3)
    return black.rotate(90, expand=True), red.rotate(90, expand=True)  # в родную ориентацию 122x250


def main():
    text = " ".join(sys.argv[1:]) or "Hello World"
    epd = EPD()
    try:
        epd.init()
        epd.display(*render(text))
        epd.sleep()
    finally:
        epd.close()


if __name__ == "__main__":
    main()
