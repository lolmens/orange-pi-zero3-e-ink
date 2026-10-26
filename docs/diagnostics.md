# Диагностика

Приёмы, которыми нашли все [грабли](pitfalls.md). Для большинства хватает ssh и прав из `setup.sh`.

> [!CAUTION]
> Ни в одном из приёмов не трогайте **пин 7 (PC9, линия 73)**: это прерывание PMIC AXP313A
> ([грабли 10](pitfalls.md#10-пин-7-pc9--прерывание-pmic)).

## 1. Назначены ли пины SPI

У узла SPI1 в живом device tree должно быть свойство `pinctrl-0`:

```bash
ls /proc/device-tree/soc/spi@5011000/pinctrl-0
```

Нет файла — значит, контроллер включён, а на разъём ничего не выходит
([грабли 6](pitfalls.md#6-overlay-spidev1_x-не-назначает-пины)).

С root можно посмотреть, кому отданы сами пины, — в строках PH6–PH9 должен значиться `5011000.spi`:

```bash
sudo grep -E '\(PH[6-9]\)' /sys/kernel/debug/pinctrl/300b000.pinctrl/pinmux-pins
```

## 2. Проверка overlay до перезагрузки

Накладываем overlay на настоящий DTB платы в том же порядке, что и загрузчик
(сначала `overlays=`, потом `user_overlays=`), и смотрим, что получил SPI1. Root не нужен.

```bash
cd /boot/dtb/allwinner
dtc -@ -q -I dts -O dtb -o /tmp/spi1-pins.dtbo ~/epaper/spi1-pins.dts
fdtoverlay -i sun50i-h618-orangepi-zero3.dtb -o /tmp/merged.dtb \
    overlay/sun50i-h616-gpu.dtbo overlay/sun50i-h616-spidev1_1.dtbo /tmp/spi1-pins.dtbo

fdtget -l /tmp/merged.dtb /soc/spi@5011000            # дочерние узлы: spidev@1
fdtget /tmp/merged.dtb /soc/spi@5011000 pinctrl-0     # phandle групп пинов
for n in spi1-pins spi1-cs0-pin spi1-cs1-pin; do
    echo "$n: phandle $(fdtget /tmp/merged.dtb /soc/pinctrl@300b000/$n phandle)," \
         "pins $(fdtget /tmp/merged.dtb /soc/pinctrl@300b000/$n pins)"
done
```

`pinctrl-0` должен ссылаться на `spi1-pins` (PH6 PH7 PH8) и `spi1-cs1-pin` (PH9).
Именно эта проверка показала, что `spi1-cs0-pin` — это PH5
([грабли 7](pitfalls.md#7-cs-на-пине-24--это-cs1-а-не-cs0)).

## 3. Проба подтяжками: подключён ли провод

Внутренние подтяжки H618 слабые (порядка 100 кОм). Читаем каждый пин сначала с подтяжкой вверх,
потом вниз:

| Вверх | Вниз | Значит |
|---|---|---|
| 1 | 0 | Пин висит в воздухе: ничего не подключено или вход без подтяжки |
| 1 | 1 | Что-то снаружи держит 1 (подтяжка на модуле или на плате) |
| 0 | 0 | Что-то снаружи держит 0 (например, выход другой микросхемы) |

```python
import time
import gpiod
from gpiod.line import Bias, Direction

# физ. пин -> (вывод, линия в gpiochip1). Пин 7 (PC9) намеренно исключён.
PINS = {3: ("PH5", 229), 5: ("PH4", 228), 8: ("PH2", 226), 10: ("PH3", 227),
        11: ("PC6", 70), 12: ("PC11", 75), 13: ("PC5", 69), 15: ("PC8", 72),
        16: ("PC15", 79), 18: ("PC14", 78), 22: ("PC7", 71), 26: ("PC10", 74)}

with gpiod.Chip("/dev/gpiochip1") as chip:
    for pin, (name, line) in PINS.items():
        values = []
        for bias in (Bias.PULL_UP, Bias.PULL_DOWN):
            settings = gpiod.LineSettings(direction=Direction.INPUT, bias=bias)
            with chip.request_lines(consumer="probe", config={line: settings}) as req:
                time.sleep(0.01)
                values.append(req.get_value(line).value)
        print(f"пин {pin:2} {name:5} вверх={values[0]} вниз={values[1]}")
```

После пробы пины остаются входами с подтяжкой вниз.

Эталон для этой платы с подключённым модулем, дисплей в покое:

| Пин | Вывод | Вверх | Вниз | Что это |
|---|---|---|---|---|
| 3, 5 | PH5, PH4 | 1 | 1 | Держатся в 1 чем-то на плате (к модулю не подключены) |
| 8, 10 | PH2, PH3 | 1 | 0 | Свободны |
| 11 | PC6 | 1 | 1 | RES: подтяжка вверх на модуле — провод на месте |
| 12, 16, 18 | PC11, PC15, PC14 | 1 | 1 | Держатся в 1 чем-то на плате (к модулю не подключены) |
| 13 | PC5 | 0 | 0 | BUSY: модуль держит 0 в покое — провод на месте |
| 15, 26 | PC8, PC10 | 1 | 0 | Свободны |
| 22 | PC7 | 1 | 0 | D/C: вход без подтяжки, этой пробой не проверить |

Входы SPI (CLK, MOSI, CS) на модуле тоже без подтяжек, поэтому их так не проверить.

## 4. Как ведёт себя BUSY во время обновления

Скрипт держит линии всё время работы, и второй процесс их не получит. Поэтому следим за BUSY
из того же процесса, через классы из `hello_epaper.py` (запускать из папки со скриптом):

```python
import time
import hello_epaper as h

epd = h.EPD()
try:
    epd.init()
    black, red = h.render("BUSY test")
    for ram, image in ((0x24, black), (0x26, red)):
        epd.command(0x4E, 0x00)
        epd.command(0x4F, 0x00, 0x00)
        epd.command(ram)
        epd.data(image.tobytes())
    epd.command(0x22, 0xF7)
    epd.command(0x20)
    t0, prev = time.monotonic(), None
    while (t := time.monotonic() - t0) < 40:
        if (busy := epd.busy()) != prev:
            print(f"{t:6.2f} с  BUSY = {int(busy)}")
            prev = busy
        time.sleep(0.01)
    epd.sleep()
finally:
    epd.close()
```

У исправного модуля сразу будет `BUSY = 1`, а через 20–30 с — `BUSY = 0`.
У нашего модуля всё время `BUSY = 0`.

## 5. Программный SPI в обход контроллера

Если непонятно, виноваты провода или настройка SPI, можно передавать SPI программно, дёргая пины
как обычные GPIO. Это работает, только пока PH6–PH9 не отданы SPI, то есть без overlay `spi1-pins`.
Чтобы воспользоваться приёмом на настроенной плате, уберите `spi1-pins` из `user_overlays`
в `/boot/armbianEnv.txt` и перезагрузитесь.

```python
import gpiod
from gpiod.line import Direction, Value

CLK, MOSI, CS, DC = 230, 231, 233, 71  # PH6, PH7, PH9, PC7
V = (Value.INACTIVE, Value.ACTIVE)
req = gpiod.request_lines("/dev/gpiochip1", consumer="bitbang", config={
    (DC, CS): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
    (CLK, MOSI): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
})


def xfer(dc, data):
    """SPI mode 0, старший бит вперёд: бит выставляется при CLK = 0, защёлкивается по фронту CLK."""
    req.set_values({DC: V[dc], CS: Value.INACTIVE})
    for byte in data:
        for i in range(7, -1, -1):
            req.set_values({CLK: Value.INACTIVE, MOSI: V[(byte >> i) & 1]})
            req.set_value(CLK, Value.ACTIVE)
    req.set_values({CLK: Value.INACTIVE, CS: Value.ACTIVE})


def cmd(c, *data):
    xfer(0, [c])
    if data:
        xfer(1, data)
```

Дальше — та же последовательность команд, что и в `hello_epaper.py`. Скорость — около 5 КБ/с:
два слоя по 4000 байт уходят за 1.6 с, на фоне 20–30-секундного обновления это незаметно.

Именно так подтвердили, что провода исправны, а SPI не выходит на разъём из-за device tree:
программный SPI очистил дисплей с первой попытки.

## 6. BUSY мультиметром

Запустите `hello_epaper.py` и во время обновления (20–30 с) измерьте напряжение BUSY относительно GND:

1. на выводе BUSY модуля;
2. если там мало — на контакте 9 шлейфа панели (BUSY на 24-контактном шлейфе).

| Результат | Вывод |
|---|---|
| ~3.3 В на выводе модуля | BUSY исправен, ищите проблему в проводе до пина 13 |
| ~3.3 В на шлейфе, мало на выводе модуля | Обрыв дорожки или пайка на плате модуля |
| Мало и на шлейфе | Контакт шлейфа в разъёме или сама панель |

Наши замеры — в [граблях 9](pitfalls.md#9-busy-не-работает--дефект-модуля).
