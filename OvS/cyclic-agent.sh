#!/bin/bash

# parameters
ifaces=(eth0 eth1 eth2 eth3 wlan1)
#ifaces=(eth0 eth1 eth2 eth3)
#ifaces=(eth0 eth2 eth1 eth3)
#ifaces=(eth0 eth1 wlan1 wlan1)
#ifaces=(eth0 eth1 eth2 wlan1)
serviceIP=192.168.100.10
tperiod=20

# switching cycle
for ((i=0; i<10000; i++)); do
  iface=${ifaces[($i)%${#ifaces[@]}]}
  ../OvS/switch-ovs.sh $iface $serviceIP
  sleep $tperiod
done
