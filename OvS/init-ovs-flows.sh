#!/bin/bash

# first parameters are the name of the interfaces to be used
IF1=$1
IF2=$2
IF3=$3
IF4=$4
IF5=$5

# next the IP addresses of the mikrotik devices
IP1=$6
IP2=$7
IP3=$8
IP4=$9
IP5=${10}

# last parameter is the IP address to ping to assess network connectivity and refresh switches' fdb
GW_IP=${11}
IFSTART=$IF1

# clear flow table
ovs-ofctl del-flows br-60G

# rules for input traffic without loop
ovs-ofctl add-flow br-60G priority=10,in_port=$IF1,actions=output:LOCAL
ovs-ofctl add-flow br-60G priority=10,in_port=$IF2,actions=output:LOCAL
ovs-ofctl add-flow br-60G priority=10,in_port=$IF3,actions=output:LOCAL
ovs-ofctl add-flow br-60G priority=10,in_port=$IF4,actions=output:LOCAL
ovs-ofctl add-flow br-60G priority=10,in_port=$IF5,actions=output:LOCAL

# rules for output traffic - we begin from IF1
ovs-ofctl add-flow br-60G priority=10,cookie=0x10,in_port='br-60G',actions=output:$IFSTART

# rules for contacting RAT devices
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x806,nw_dst=$IP1,actions=output:$IF1
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x800,nw_dst=$IP1,actions=output:$IF1
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x806,nw_dst=$IP2,actions=output:$IF2
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x800,nw_dst=$IP2,actions=output:$IF2
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x806,nw_dst=$IP3,actions=output:$IF3
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x800,nw_dst=$IP3,actions=output:$IF3
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x806,nw_dst=$IP4,actions=output:$IF4
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x800,nw_dst=$IP4,actions=output:$IF4
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x806,nw_dst=$IP5,actions=output:$IF5
ovs-ofctl add-flow br-60G priority=11,in_port='br-60G',dl_type=0x800,nw_dst=$IP5,actions=output:$IF5

# loop avoidance
ovs-ofctl add-flow br-60G priority=0,actions=drop

# enable all ports
ip link set $IF1 up
ip link set $IF2 up
ip link set $IF3 up
ip link set $IF4 up
ip link set $IF5 up
sleep 3

# update network switches' forwarding database and test switching effectiveness
ping -c 1 -s 1 -W 1 $GW_IP 1>/dev/null 2>&1  # The fast way to ping
if [ $? -ne 0 ]; then
  echo "ERROR: interface" $IFSTART "not working or" $GW_IP "unreachable"
  exit 1
else 
  echo "Interface" $IFSTART "running ..."
  exit 0
fi


