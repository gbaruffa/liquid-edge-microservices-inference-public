#!/usr/bin/python3
from kubernetes.client.rest import ApiException
from kubernetes import client, config, utils
import threading
import time
import subprocess
import signal

config.load_kube_config()

reqnum_list = list()
keep_processing = True

def signal_handler(sig, frame):
  print('Stopping all')
  global keep_processing
  keep_processing = False

def thread_function(pod_name, node_name, index):
  global reqnum_list
  global keep_processing
  reqnum_list[index] = 0
  while keep_processing:
    try:
      api_instance = client.CoreV1Api()
      api_response = api_instance.read_namespaced_pod_log(name=pod_name, namespace='istio-system', follow=True, _preload_content=False, since_seconds=1)
      for line in api_response:
        if "ObjectDetect" in str(line):
          reqnum_list[index] = reqnum_list[index] + 1
        if not keep_processing:
          break
    except ApiException as e:
      print('Found exception in reading the logs', e)
      time.sleep(1)

signal.signal(signal.SIGINT, signal_handler)

cloud_name = "nodenamecloud"
node_name_list = ("nodename1", "nodename2", "nodename3", "nodename4", "nodename5")
pod_name_list = ("istio-ingressgateway-5c9b64675d-hqrdh", "istio-ingressgateway-5c9b64675d-ndplt", "istio-ingressgateway-5c9b64675d-h2fhx", "istio-ingressgateway-5c9b64675d-4spzp", "istio-ingressgateway-5c9b64675d-qpk9g")
reqnum_list = [0] * len(node_name_list)
lastuse_list = [0] * len(node_name_list)
inuse_list = [False] * len(node_name_list)
th = list()
for index, pod_name in enumerate(pod_name_list):
  x = threading.Thread(target=thread_function, daemon=True, args=(pod_name, node_name_list[index], index))
  th.append(x)
  x.start()

print("Starting the cloud")
result = subprocess.run([f"kubectl apply -f pyc-detection-gpu-pod-cloud.yaml"], shell=True)

reqnum_list_prev = [0] * len(reqnum_list)
last_time = 0
numworkers = 0
while keep_processing:
  reqnum_list_curr = reqnum_list[:]
  rps_list = [(element1 - element2) / (time.time() - last_time) for (element1, element2) in zip(reqnum_list_curr, reqnum_list_prev)]
  last_time = time.time()
  for index, node_name in enumerate(node_name_list):
    cmanifest = f"pyc-detection-gpu-pod-{node_name}.yaml"
    if rps_list[index] > 0:
      if node_name != cloud_name and not inuse_list[index]:
        print("Starting service on", node_name)
        result = subprocess.run([f"kubectl apply -f {cmanifest}"], shell=True)
        numworkers = numworkers + 1
        inuse_list[index] = True
      lastuse_list[index] = time.time()
    elif inuse_list[index] and time.time() - lastuse_list[index] > 3*60:
      print("Terminating service on", node_name)
      result = subprocess.run([f"kubectl delete -f {cmanifest}"], shell=True)
      numworkers = numworkers - 1
      inuse_list[index] = False

  windex = max((v, i) for i, v in enumerate(rps_list))[1]
  if rps_list[windex] > 0.2:
    print("Requests/s:", rps_list, "Receiving node:", node_name_list[windex])
  else:
    print("Requests/s:", rps_list, "Receiving node: none")
    windex = None
  reqnum_list_prev = reqnum_list_curr[:]
  time.sleep(1)

print("Stopping the cloud and the edge")
result = subprocess.run([f"kubectl delete -f pyc-detection-gpu-pod-cloud.yaml"], shell=True)
if numworkers > 0:
  result = subprocess.run([f"kubectl delete -f pyc-detection-gpu-pod-apprendo.yaml"], shell=True)
