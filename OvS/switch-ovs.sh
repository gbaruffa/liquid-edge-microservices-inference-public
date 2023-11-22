#!/bin/bash

# first parameter is the name of the interface to be used
# second paramenter is the IP address to ping to assess network connectivity and refresh the switch fdb
IF=$1
GW_IP=$2

# redirect output traffic to new interface
ovs-ofctl mod-flows br-60G priority=10,cookie=0x10/0xFF,in_port='br-60G',actions=output:$IF
ovs-dpctl del-flows
echo $IF > /tmp/currentovsport
sleep 0.1

# update network switches' forwarding database and test switching effectiveness
ping -c 1 -s 1 -W 1 $GW_IP 1>/dev/null 2>&1  # The fast way to ping
if [ $? -ne 0 ]; then
  echo "ERROR: interface" $IF "not working or" $GW_IP "unreachable"
  exit 1
else 
  echo "Interface" $IF "running"
  exit 0
fi
