# LIQUID EDGE Microservices Inference

![LIQUID EDGE Logo](../doc/liquid_edge_logo28.png)

> These programs are a part of the system used for the LIQUID EDGE PRIN 2017 project demonstrator.

## Open vSwitch configuration

The robot hosts 4 mmWave NICs (MikroTik wAP 60G), 1 Wi-Fi dongle, 1 USB3 hub, and 3 USB-Ethernet adapters (Benfei Asix AX88179A).

The aim of this section is to explain how the mobile node networking can be setup so as to achieve an error-proof transmission of packets, even during handovers between the 60 GHz stations and access points.

The first step is to setup four separate Ethernet interfaces: one uses the native Gigabit Ethernet of the Raspberry; for the other three, instead, we use USB3-to-Ethernet adapters with an [ASIX AX88179 chip](https://www.asix.com.tw/en/product/USBEthernet/Super-Speed_USB_Ethernet/AX88179).

The adapters can be bound to a specific GbE interface in the OS kernel, by specifying the proper `udev` rules. However, this procedure appears to be not guaranteed to work in Raspberry OS: USB ethernet devices have their interfaces assigned randomly. In order to ensure the correct pairing and ordering, attach the adapters to the USB3 hub in order: the first (most distant from the cable) will be `eth1`, the second `eth2`, and the third, well, `eth3`. After that, run the `reset_usb_hub.sh` script to get the correct ordering any time you need (generally after every reboot).

### Software-defined bridge

The SDN bridge is setup using _[OvS](https://www.openvswitch.org/)_. To install the package type

```cli
$ sudo apt install openvswitch-switch openvswitch-common 
```

Then, create the bridge and add all the required ports

```cli
$ ovs-vsctl add-br br-60G
$ ovs-vsctl add-port br-60G eth0 
$ ovs-vsctl add-port br-60G eth1 
$ ovs-vsctl add-port br-60G eth2
$ ovs-vsctl add-port br-60G eth3
$ ovs-vsctl add-port br-60G wlan1
```

The layout should be like this one

```cli
$ ovs-vsctl show
876*************************
    Bridge br-60G
        Port br-60G
            Interface br-60G
                type: internal
        Port eth1
            Interface eth1
        Port wlan1
            Interface wlan1
        Port eth0
            Interface eth0
        Port eth3
            Interface eth3
        Port eth2
            Interface eth2
    ovs_version: "2.15.0"
```

## Operation

The bridge is operated as follows:

* verify that the Ethernet dongles are physically placed
* reorder correctly the dongles with `reset_usbhub_wlan.sh`
* verify with `dmesg` that ethernet interface names and dongles are matched correctly
* prepare the bridge with `setup-ovs.sh`
* `ping -c 1 192.168.100.10` and verify it is responding
* start `cyclic-agent.sh` to periodically switch the interfaces, or `best-agent.py`to use the best one
* `ping 192.168.100.10` and verify it is responding during handovers

## References

1. ASIX, "[AX88179 - USB3.0 to 10/100/1000M Gigabit Ethernet Controller](https://www.asix.com.tw/en/product/USBEthernet/Super-Speed_USB_Ethernet/AX88179)," Dec. 2020
2. R. Marples, "[dhcpcd.conf — dhcpcd configuration file](https://manpages.debian.org/buster/dhcpcd5/dhcpcd.conf.5.en.html)," _Debian_, Sep. 2018
3. E. Mulyana, "[PiOVS: Raspberry Pi Open vSwitch](https://www.telematika.org/post/piovs-raspberry-pi-open-vswitch/)," _Telematika.ORG_, Feb. 2018
4. B. Pfaff, J. Pettit, T. Koponen, E. J. Jackson, A. Zhou, J. Rajahalme, J. Gross, A. Wang, J. Stringer, P. Shelar, K. Amidon, M. Casado, "[The Design and Implementation of Open vSwitch](https://www.openvswitch.org/support/slides/nsdi2015-slides.pdf)," _USENIX NSDI 2015_, Oakland, CA, USA, May 2015
5. Kotte, "[How to bind USB device under a static name?](https://unix.stackexchange.com/a/66916),", _GitHub_, Mar. 2013 
6. Enbis, "[How udev rules can help us to recognize a usb-to-serial device over /dev/tty interface](https://dev.to/enbis/how-udev-rules-can-help-us-to-recognize-a-usb-to-serial-device-over-dev-tty-interface-pbk)," _dev.to_, Jan. 2020
7. Peterh, "[How to set up an usb/ethernet interface in Linux?](https://unix.stackexchange.com/a/386170)," _GitHub_, Jul. 2020
8. VarHowto Editor, "[How to Install ROS Noetic on Raspberry Pi 4](https://varhowto.com/install-ros-noetic-raspberry-pi-4/)," _VarHowTo_, Dec. 2020
9. "[How to Setup a Wireless Access Point on the Raspberry Pi](https://learn.pi-supply.com/make/how-to-setup-a-wireless-access-point-on-the-raspberry-pi/)," _MakerZone_, Apr. 2020
10. https://forums.raspberrypi.com/viewtopic.php?t=253446
