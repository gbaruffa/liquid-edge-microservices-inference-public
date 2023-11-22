#!/bin/bash
echo "Setting up OVS flows and rules"
./init-ovs-flows.sh eth0 eth1 eth2 eth3 wlan1 192.168.100.82 192.168.100.83 192.168.100.84 192.168.100.88 192.168.100.90 192.168.100.10
