#!/bin/bash

# replace '2' with actual hub bus number as shown by lsusb -t: {bus}-{port}(.{subport})
port="usb2" 

bind_usb() {
  echo "$1" >/sys/bus/usb/drivers/usb/bind
}

unbind_usb() {
  echo "$1" >/sys/bus/usb/drivers/usb/unbind
}

echo -n "Resetting USB3 Hub for predictable interface names... "
unbind_usb "$port"
sleep 1
bind_usb "$port"
sleep 5
ip link show eth1
ip link show eth2
ip link show eth3
echo "done"

echo "Resetting WLAN1... "
#killall wpa_supplicant
#wpapid=$(pgrep -f "wpa_supplicant -B -c/etc/wpa_supplicant/wpa_supplicant.conf -iwlan1")
#kill $wpapid
wpa_supplicant -B -c/etc/wpa_supplicant/wpa_supplicant.conf -iwlan1
wpa_cli -i wlan1 reconfigure
sleep 4
cat /proc/net/wireless
echo "done"