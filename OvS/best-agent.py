#!/usr/bin/env python
"""This agent swiches the link depending on the available links qualities"""
import sys
import yaml
import os
import routeros_api
import subprocess
import threading
import time
from signal import signal, SIGTERM, SIGINT
from termcolor import cprint
import math
#from pythonping import ping

# global variables
keepRunning = True
serviceIP = None

def handle_sigs(*_):
  """Handle the OS signals"""
  print("\nReceived shutdown signal")
  global keepRunning
  keepRunning = False
  print("Shut down gracefully")


def switch_radiores(radiores):
  """Switch the IP link to this radio resource"""
  cprint(f"switching to {radiores['iface']}", 'green')
  global serviceIP
  if radiores['techno'] in ('802.11ad', '802.11b/g/n'):
    # use OvS
    result = subprocess.run([f"ovs-ofctl mod-flows br-60G priority=10,cookie=0x10/0xFF,in_port='br-60G',actions=output:{radiores['iface']}"], shell=True)
    if result.returncode == 0:
      result = subprocess.run(["ovs-dpctl", "del-flows"])
      if result.returncode == 0:
        time.sleep(0.05)
        with open("/tmp/currentovsport","w") as f:
          f.write(radiores['iface'])
        result = subprocess.run(["ping", "-c", "1", "-s", "1", "-W", "1", serviceIP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
        #response = ping(gatewayIP, count=1, size=1, timeout=1)
        #if response.success() == True:
          cprint(f"ERROR: interface {radiores['iface']} not working or {serviceIP} unreachable", 'red')
        else:
          print("Interface", radiores['iface'], "running")
      else:
        cprint("Could not flush the datapath", 'red')
    else:
      cprint("Could not change the flow", 'red')
  else:
    cprint("Unknown switching method", 'red')
  pass


def radiores_thread(radiores):
  """Thread dedicated to the monitoring of a radio resource"""
  print(f"Radio resource \"{radiores['identifier']}\" started")
  lastTime = 0
  discStatus = dict({'connected': False})
  radiores['status'] = discStatus
  while keepRunning:
    if time.time() - lastTime > radiores['sleep']:
      lastTime = time.time()
      lastStatus = radiores['status']
      tempStatus = discStatus
      if radiores['techno'] == '802.11ad':
        # IEEE 802.11ad 60 GHz radio technology
        try:
          res = api.get_resource('/interface/w60g').call('monitor', {'numbers': '0', 'once': ''})
          tempStatus = {**tempStatus, **res[0]}
          tempStatus['connected'] = True if tempStatus['connected'] == 'true' else False
          tempStatus['distance'] = float(tempStatus['distance'].replace('m', ''))
          tempStatus['tx-phy-rate'] = float(tempStatus['tx-phy-rate'])
          #print(tempStatus)
        except:
          try:
            print(f"connecting {radiores['identifier']}...", end=" ")
            connection = routeros_api.RouterOsApiPool(radiores['ipaddress'], username=radiores['user'], password=radiores['password'], plaintext_login=True)
            api = connection.get_api()
            res = api.get_resource('/system/identity').get()
            tempStatus['name'] = res[0]['name']
            res = api.get_resource('/interface/ethernet').get()
            tempStatus['hwaddress'] = res[0]['mac-address']
            print("connected!")
          except:
            print("connection timed out")
            pass
      elif radiores['techno'] == '802.11b/g/n':
        # IEEE 802.11b/g/n 2.4 GHz radio technology
        tempStatus['connected'] = False
        tempStatus['rssi'] = -math.inf
        tempStatus['signal'] = 0
        tempStatus['distance'] = math.inf
        tempStatus['tx-phy-rate'] = 0e6
        try:
          if os.path.isfile("/proc/net/wireless") and os.access("/proc/net/wireless",os.R_OK):
            pnwfile = open("/proc/net/wireless",'r')
            lnum = 1
            for line in pnwfile:
              if lnum >= 3:
                toks = line.split()
                if toks[0] == radiores['iface']+":":
                  tempStatus['connected'] = True
                  tempStatus['rssi'] = float(toks[3])
                  tempStatus['signal'] = float(toks[2])
                  tempStatus['distance'] = math.inf
                  tempStatus['tx-phy-rate'] = 0e6
                  tempStatus['remote-address'] = ""
                  break
                  #print(toks)
              lnum = lnum + 1
            pnwfile.close()
          #print(tempStatus)
        except:
          pass

      # assign the results
      radiores['status'] = tempStatus

      # keep the connection just for one time update
      if not radiores['status']['connected'] and lastStatus['connected']:
        radiores['status'] = lastStatus
        lastStatus = discStatus

    # try to check very often, actual check depends on the specified monitoring time
    time.sleep(0.1)

  # close the connection
  try:
    if radiores['techno'] == '802.11ad':
      connection.disconnect()
  except:
    pass
  print(f"radio resource \"{radiores['identifier']}\" stopped")


def main():
  """Main function"""
  # This script must be run as root!
  if not os.geteuid() == 0:
    sys.exit('This script must be run as root!')

  # read the configuration file
  try:
    with open(sys.argv[1]) as stream:
      config = yaml.load(stream, Loader=yaml.FullLoader) 
  except:
    with open("robot-rats.yaml") as stream:
    #with open("config/nodes/raspi01/rssimonitor/robot-rats.yaml") as stream:
      try:
        config = yaml.load(stream, Loader=yaml.FullLoader) 
      except:
        print("No configuration file found")

  # these are all our radioresources
  radioresources = config['radioresources']
  global serviceIP
  serviceIP = config['serviceIP']

  # we start the watching threads
  thrs = []
  for radiores in radioresources:
    radiores['sleep'] = config['tmon']
    radiores['status'] = dict({'connected': False})
    thrs.append(threading.Thread(target=radiores_thread, args=(radiores,)))
    thrs[-1].start()

  # open logging file
  lf = open("logfile.csv", 'w')
  lf.write('"time"')
  for radiores in radioresources:
    lf.write(',"'+radiores['identifier']+'",bsid"')
  lf.write(',"best","switch"\n')

  # continuously find the best radio resource to use
  metrics = [-math.inf]*len(radioresources)
  rssis = [-math.inf]*len(radioresources)
  quals = [0]*len(radioresources)
  rates = [0.0]*len(radioresources)
  dists = [math.inf]*len(radioresources)
  last_s_max = -1
  prog_start_time = time.time()
  while keepRunning:

    # find the metric
    s_max = -1
    metric_max = -math.inf
    for s in range(len(radioresources)):
      if radioresources[s]['status']['connected']:
        try:
          rssis[s] = float(radioresources[s]['status']['rssi'])
          dists[s] = radioresources[s]['status']['distance']
          quals[s] = float(radioresources[s]['status']['signal'])
          rates[s] = float(radioresources[s]['status']['tx-phy-rate'])
        except:
          rssis[s] = -math.inf
          dists[s] = math.inf
          quals[s] = 0.0
          rates[s] = 0.0
      else:
        rssis[s] = -math.inf
        dists[s] = math.inf
        quals[s] = 0.0
        rates[s] = 0.0
      metrics[s] = (rssis[s] + 120) * quals[s]
      if math.isnan(metrics[s]):
        metrics[s] = -math.inf
      if metrics[s] > metric_max:
        metric_max = metrics[s]
        s_max = s
    print(f"{time.time() - prog_start_time:.2f}", rssis, quals, metrics, rates)
    lf.write("%f" % (time.time()))
    for s in range(len(radioresources)):
      #print(radioresources[s])
      lf.write(',%.1f,"%s"' % (rssis[s], radioresources[s]['status']['remote-address'] if radioresources[s]['status']['connected'] else ""))

    # find the best one
    #print(s_max, last_s_max, metric_max, rssis[s_max], rssis[last_s_max])
    if s_max != -1 and metric_max > -math.inf:
      cprint(f"Best: {radioresources[s_max]['identifier']} ({radioresources[s_max]['iface']}) at {rssis[s_max]}dBm with weight {metric_max}", 'yellow')
      if last_s_max == -1 or (s_max != last_s_max and metrics[s_max] >= metrics[last_s_max] + config['dmetric']):
        # the best one is changed, switch
        switch_radiores(radioresources[s_max])
        last_s_max = s_max
        lf.write(',%d,1\n' % (s_max))
      else:
        lf.write(',%d,0\n' % (s_max))
    else:
      cprint("No link available", 'red')
      lf.write(',-1,0\n')

    # sleep a little
    time.sleep(config['tdec'])

  # we close the threads
  for thr in thrs:
    thr.join()

  # close the log
  lf.close()

if __name__ == "__main__":
  # register signals
  signal(SIGTERM, handle_sigs)
  signal(SIGINT, handle_sigs)
  
  # Go!
  main()
