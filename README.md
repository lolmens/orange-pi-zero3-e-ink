# Orange Pi Zero 3 + e-paper WeAct 2.13"

Выводит текст по центру трёхцветного (чёрный / белый / красный) e-paper дисплея
WeAct Studio 2.13" и обводит экран красной рамкой. Python, аппаратный SPI через `spidev`,
GPIO через libgpiod v2, отрисовка текста — Pillow.

```
┌────────────────────────────┐   ← красная рамка
│                            │
│        Hello World         │   ← чёрный текст
│                            │
└────────────────────────────┘
```

## Железо

| | |
|---|---|
| Плата | Orange Pi Zero 3 (Allwinner H618) |
| ОС | Armbian 26.11 (Debian 13 trixie), ядро 6.18 `current-sunxi64` |
| Дисплей | WeAct Studio e-Paper Module 2.13", трёхцветный: контроллер SSD1680, 122×250 |

## Подключение

| Модуль | Пин разъёма 26-pin | Вывод H618 | В Linux |
|---|---|---|---|
| VCC | 1 | 3.3 В | — |
| GND | 6 | GND | — |
| SDA (DIN) | 19 | PH7 — SPI1 MOSI | `/dev/spidev1.1` |
| SCL (CLK) | 23 | PH6 — SPI1 CLK | `/dev/spidev1.1` |
| CS | 24 | PH9 — SPI1 **CS1** | `/dev/spidev1.1` |
| D/C | 22 | PC7 | `gpiochip1`, линия 71 |
| RES | 11 | PC6 | `gpiochip1`, линия 70 |
| BUSY | 13 | PC5 | `gpiochip1`, линия 69 |

> [!WARNING]
> Распиновки «Orange Pi Zero», которые гуляют по сети (с именами PA0–PA3), относятся к старой
> плате на H3. Физические номера пинов совпадают, а имена выводов — нет.
> **Пин 7 (PC9) не трогайте**: это линия прерывания PMIC AXP313A.

## Установка

Файлы должны лежать на плате в одной папке — `setup.sh` берёт `spi1-pins.dts` рядом с собой.

```bash
ssh <плата> mkdir -p epaper
scp hello_epaper.py setup.sh spi1-pins.dts <плата>:epaper/
ssh -t <плата> 'sudo bash epaper/setup.sh && sudo reboot'
```

`setup.sh` (повторный запуск безопасен):

- ставит `python3-libgpiod`, `python3-spidev`, `python3-pil`, `fonts-dejavu-core`, `device-tree-compiler`;
- создаёт группы `gpio` и `spi`, добавляет в них пользователя и кладёт udev-правило — скрипт работает без `sudo`;
- компилирует `spi1-pins.dts` в `/boot/overlay-user/spi1-pins.dtbo`;
- в `/boot/armbianEnv.txt` меняет overlay `spidev1_0` на `spidev1_1` и добавляет `user_overlays=spi1-pins`
  (копия исходного файла — `armbianEnv.txt.bak-epaper`).

Зачем нужен свой overlay и почему `spidev1.1`, а не `spidev1.0`, — в [граблях](docs/pitfalls.md).

## Запуск

```bash
python3 ~/epaper/hello_epaper.py                 # Hello World
python3 ~/epaper/hello_epaper.py "Любой текст"   # размер шрифта подбирается под ширину
```

Полное обновление трёхцветной панели идёт 20–30 секунд, экран при этом несколько раз мигает —
так и должно быть. После обновления дисплей уходит в глубокий сон, картинка остаётся без питания.

## Известная проблема: BUSY

На этом экземпляре модуля линия BUSY неисправна: во время обновления она поднимается до
~0.3 В вместо ~3.3 В, плата видит постоянный 0. Скрипт это замечает, пишет предупреждение
и ждёт фиксированные 30 секунд. С исправным модулем скрипт сам начнёт ориентироваться на BUSY.
Подробности замеров — в [граблях](docs/pitfalls.md#9-busy-не-работает--дефект-модуля).

## Документация

- [Как это работает](docs/how-it-works.md) — путь сигнала, протокол SSD1680, формат памяти кадра, настройка системы.
- [Грабли](docs/pitfalls.md) — всё, на что наступили по дороге, с симптомами и решениями.
- [Диагностика без осциллографа](docs/diagnostics.md) — как проверить провода, device tree и BUSY программно.

## Файлы

| Файл | Что это |
|---|---|
| `hello_epaper.py` | Драйвер SSD1680 и вывод текста |
| `setup.sh` | Однократная настройка платы (пакеты, права, overlay) |
| `spi1-pins.dts` | Device tree overlay: отдаёт SPI1 пины PH6–PH9 |
