#!/bin/bash
# Однократная настройка: зависимости, доступ к SPI/GPIO без sudo, пины SPI1.
# Запуск: sudo bash setup.sh (повторный запуск безопасен)
set -euo pipefail

USER_NAME="${SUDO_USER:?запустите через sudo}"
DIR="$(dirname "$(readlink -f "$0")")"

apt-get install -y python3-libgpiod python3-spidev python3-pil fonts-dejavu-core device-tree-compiler

ENV=/boot/armbianEnv.txt

add_overlay() {  # add_overlay <ключ> <имя>: дописать имя в строку ключа, если его там нет
    if grep -q "^$1=" "$ENV"; then
        grep -qE "^$1=(.* )?$2( |\$)" "$ENV" || sed -i "/^$1=/ s/\$/ $2/" "$ENV"
    else
        echo "$1=$2" >> "$ENV"
    fi
}

mkdir -p /boot/overlay-user
dtc -@ -q -I dts -O dtb -o /boot/overlay-user/spi1-pins.dtbo "$DIR/spi1-pins.dts"
cp -n "$ENV" "$ENV.bak-epaper"
sed -i -e '$a\' "$ENV"
# CS на пине 24 (PH9) — аппаратный CS1 контроллера SPI1, поэтому spidev1_1 вместо spidev1_0
sed -i -E '/^overlays=/ s/ ?\bspidev1_0\b//' "$ENV"
add_overlay overlays spidev1_1
add_overlay user_overlays spi1-pins
grep -E '^(overlays|user_overlays)=' "$ENV"

groupadd -f gpio
groupadd -f spi
usermod -aG gpio,spi "$USER_NAME"

cat > /etc/udev/rules.d/99-gpio-spi.rules <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
SUBSYSTEM=="spidev", GROUP="spi", MODE="0660"
EOF
udevadm control --reload
udevadm trigger --subsystem-match=gpio --subsystem-match=spidev
udevadm settle

ls -l /dev/gpiochip* /dev/spidev*
echo "Готово. Перезагрузите плату (sudo reboot), чтобы применился overlay spi1-pins."
