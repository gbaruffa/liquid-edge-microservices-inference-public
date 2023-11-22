from concurrent import futures
from logging import exception
import grpc
from detection_pb2 import (DetectedYolo, YoloDetectionResponse)
import detection_pb2_grpc
import cv2
import numpy as np
from signal import signal, SIGTERM, SIGINT
import argparse
import sys
import time

# parse arguments
parser = argparse.ArgumentParser(description='Yolo server')
parser.add_argument("-g", "--gpu", help="Try to use the GPU (CUDA)", default=False, action='store_true', dest='usegpu')
parser.add_argument("-i", "--no-infer", help="Do not perform inference", default=None, action='store_true', dest='noinfer')

### YOLOv3 tiny ###
# parser.add_argument("-w", "--weights", help='DNN weights file', action='store_true', dest='weightsfile', default='../liquid-edge-model-zoo/Darknet/yolov3-tiny.weights')
# parser.add_argument("-c", "--config", help='DNN configuration file', action='store_true', dest='configfile', default='../liquid-edge-model-zoo/Darknet/yolov3-tiny.cfg')
# parser.add_argument("-n", "--names", help='Classes names file', action='store_true', dest='namesfile', default='../liquid-edge-model-zoo/Darknet/coco.names')

### YOLOv3 ###
parser.add_argument("-w", "--weights", help='DNN weights file', action='store_true', dest='weightsfile', default='../liquid-edge-model-zoo/Darknet/yolov3.weights')
parser.add_argument("-c", "--config", help='DNN configuration file', action='store_true', dest='configfile', default='../liquid-edge-model-zoo/Darknet/yolov3.cfg')
parser.add_argument("-n", "--names", help='Classes names file', action='store_true', dest='namesfile', default='../liquid-edge-model-zoo/Darknet/coco.names')

### YOLOv5 ###
# parser.add_argument("-w", "--weights", help='DNN weights file', action='store_true', dest='weightsfile', default='../yolov5-opencv-cpp-python/config_files/yolov5s.onnx')
# parser.add_argument("-c", "--config", help='DNN configuration file', action='store_true', dest='configfile', default='')
# parser.add_argument("-n", "--names", help='Classes names file', action='store_true', dest='namesfile', default='../yolov5-opencv-cpp-python/config_files/classes.txt')

args = parser.parse_args()


print("openCV version:", cv2.__version__)
print("python version:", sys.version)
print("grpcio version:", grpc.__version__)
print("weights:", args.weightsfile)
print("config:", args.configfile)
print("names:", args.namesfile)


def get_output_layers(net):
  """function to get the output layer names in the architecture"""
  layer_names = net.getLayerNames()
  output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]
  return output_layers


class YoloDetectionService(detection_pb2_grpc.YoloDetectionServicer):
  """This service class is devoted to Yolo detection"""
  # read pre-trained model and config file
  if not args.configfile:
    net = cv2.dnn.readNet(args.weightsfile)
  else:
    net = cv2.dnn.readNet(args.weightsfile, args.configfile)
  try:
    if args.usegpu and cv2.cuda.getCudaEnabledDeviceCount() > 0:
      net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
      net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
      print("Using CUDA")
    else:
      net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
      net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
      print("Using CPU")
  except:
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    print("Using CPU")
  if args.noinfer:
    print("Inference disabled")

  # load file with classes names
  classes = []
  with open(args.namesfile, "r") as f:
    classes = [line.strip() for line in f.readlines()]

  def YoloDetect(self, request, context):
    """This method detects the yolos in the received frame"""

    # decompress image
    starttime = time.time()
    img = cv2.imdecode(np.frombuffer(request.frame.img, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    #print(f"#{request.frame.number} size:{img.shape[1]}x{img.shape[0]}x{img.shape[2]}")

    if args.noinfer:
      return YoloDetectionResponse(number=request.frame.number, timestamp=request.frame.timestamp, yolos=[])

    # create input blob
    blob = cv2.dnn.blobFromImage(img, 1/255, (416, 416), (0, 0, 0), True, crop=False)

    # set input blob for the network
    self.net.setInput(blob)

    # run inference through the network and gather predictions from output layers
    try:
      outs = self.net.forward(get_output_layers(self.net))
    except Exception as e:
      print(f"Error inferencing: {e}")
      return YoloDetectionResponse(number=request.frame.number, timestamp=request.frame.timestamp, yolos=[])
    
    # for each detetion from each output layer get the confidence, class id, bounding box params and ignore weak detections (confidence < 0.7)
    class_ids = []
    confidences = []
    boxes = []
    ccolors = []
    for out in outs:
      for detection in out:
        scores = detection[5:]
        class_id = np.argmax(scores)
        confidence = scores[class_id]
        if confidence > 0.7:

          # object properties
          center_x = int(detection[0]*img.shape[1])
          center_y = int(detection[1]*img.shape[0])
          w = int(detection[2]*img.shape[1])
          h = int(detection[3]*img.shape[0])

          # rectangle coordinates
          x = int(center_x - w/2)
          y = int(center_y - h/2)

          # average color of the centroid
          #ccolor = np.average(np.average(img[center_y - 2:center_y + 2, center_x - 2:center_x + 2], axis=0), axis=0)
          ccolors.append(np.average(np.average(img[center_y - 2:center_y + 2, center_x - 2:center_x + 2], axis=0), axis=0))
          #ccolors.append([0, 0, 0])
          #print(ccolor)

          # put all rectangle areas
          boxes.append([x, y, w, h])

          # confidence of detected object
          confidences.append(float(confidence))

          # id of the object that was detected
          class_ids.append(class_id)

      break # this is an hack

    #print("Time", time.time() - starttime)

    # clean overlapping boxes
    indexes = cv2.dnn.NMSBoxes(boxes, confidences, 0.4, 0.6)

    # prepare detected objects array
    detected_yolos = []
    nr = 0

    # prepare response
    for i in range(len(boxes)):
      if i in indexes:
        x, y, w, h = boxes[i]
        if nr < request.max_results:
          detected_yolos.append(DetectedYolo(name=self.classes[class_ids[i]], confidence=confidences[i], x=int(x), y=int(y), w=int(w), h=int(h), r=int(ccolors[i][2]), g=int(ccolors[i][1]), b=int(ccolors[i][0])))
          nr += 1
        else:
          break

    #print(f"Detected {nr} yolos")

    return YoloDetectionResponse(number=request.frame.number, timestamp=request.frame.timestamp, yolos=detected_yolos)


def serve():
  """Serving function"""
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  detection_pb2_grpc.add_YoloDetectionServicer_to_server(YoloDetectionService(), server)
  server.add_insecure_port("[::]:50055")
  server.start()

  def handle_sigs(*_):
    print("Received shutdown signal, doing gracefully")
    all_rpcs_done_event = server.stop(30)
    all_rpcs_done_event.wait(30)

  signal(SIGTERM, handle_sigs)
  signal(SIGINT, handle_sigs)
  print("Yolo server started")
  server.wait_for_termination()


if __name__ == "__main__":
  """Go!"""
  serve()
