from concurrent import futures
import grpc
from detection_pb2_grpc import FaceDetectionStub, YoloDetectionStub
from detection_pb2 import DetectedObject, ObjectDetectionResponse, FaceDetectionRequest, YoloDetectionRequest
import detection_pb2_grpc
from signal import signal, SIGTERM, SIGINT
import os
import argparse
import socket
import struct
import sys 
from flask import Flask
from mjpeg.server import MJPEGResponse
import time
import threading
from werkzeug.serving import make_server
import os 


global jpegbuffer
dir_path = os.path.dirname(os.path.realpath(__file__))
with open(dir_path + "/liquid_edge_paused.jpg", mode='rb') as file: # b is important -> binary
  jpegbuffer = file.read()
global pausedjpegbuffer
pausedjpegbuffer = jpegbuffer
global lastjpegtime
lastjpegtime = time.time()

def extract_ip():
  st = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:       
    st.connect(('10.255.255.255', 1))
    IP = st.getsockname()[0]
  except Exception:
    IP = '127.0.0.1'
  finally:
    st.close()
  return IP


def ip2int(addr):
    return struct.unpack("!I", socket.inet_aton(addr))[0]


def int2ip(addr):
    return socket.inet_ntoa(struct.pack("!I", addr))


# parse arguments
parser = argparse.ArgumentParser(description='Object server')
parser.add_argument("addressf", help="Face server address:port", default='localhost:50053', nargs='?')
parser.add_argument("addressy", help="Yolo server address:port", default='localhost:50055', nargs='?')
parser.add_argument("-p", "--parallel", help="Parallel requests to microservices", default=True, action='store_true', dest='parallel')
parser.add_argument("-w", "--web-serve", help="Web server for camera viewing", default=False, action='store_true', dest='webserve')
args = parser.parse_args()

#print("openCV version:" + cv2.__version__)
print("python version:", sys.version)
print("grpcio version:", grpc.__version__)

# find our hostname and IP address
hostname = socket.gethostname()   
print("Computer Name:", hostname)   
hostipv4 = ip2int(extract_ip())
print("Computer IP Address:", int2ip(hostipv4))  

# open communication channel with faces
facedetection_host = os.getenv("FACEDETECTION_HOST", args.addressf)
facedetection_channel = grpc.insecure_channel(facedetection_host)
faceclient = FaceDetectionStub(facedetection_channel)
print("Face detection host:", facedetection_host)

# open communication channel with yolos
yolodetection_host = os.getenv("YOLODETECTION_HOST", args.addressy)
yolodetection_channel = grpc.insecure_channel(yolodetection_host)
yoloclient = YoloDetectionStub(yolodetection_channel)
print("YoLo detection host:", yolodetection_host)

if args.parallel:
  print("Making parallel calls to microservices")

class ObjectDetectionService(detection_pb2_grpc.ObjectDetectionServicer):
  """This service class is devoted to object detection"""


  def FaceDetectCall(self, req) -> list:
    """Perform a face request and get the response"""

    # prepare the face request
    facerequest = FaceDetectionRequest(max_results=req.max_results, frame=req.frame)

    # a list of results
    facelist = list()

    # call the face RPC
    try:
      facedetresponse = faceclient.FaceDetect(facerequest)

      # add faces to the list
      for face in facedetresponse.faces:
        if len(facelist) < req.max_results:
          facelist.append(DetectedObject(name="face", eng=0, confidence=face.confidence, x=face.x, y=face.y, w=face.w, h=face.h))
        else:
          break

    except Exception as e:
      # some problems
      print(e)

    # return the list
    return facelist


  def YoloDetectCall(self, req) -> list:
    """Perform a Yolo request and get the response"""

    # prepare the face request
    yolorequest = YoloDetectionRequest(max_results=req.max_results, frame=req.frame)

    # a list of results
    yololist = list()

    # call the face RPC
    try:
      yolodetresponse = yoloclient.YoloDetect(yolorequest)

      # add yolos to the list
      for yolo in yolodetresponse.yolos:
        if len(yololist) < req.max_results:
          yololist.append(DetectedObject(name=yolo.name, eng=1, confidence=yolo.confidence, x=yolo.x, y=yolo.y, w=yolo.w, h=yolo.h))
        else:
          break

    except:
      # some problems
      pass

    # return the list
    return yololist


  def ObjectDetect(self, request, context):
    """This method detects the objects in the received frame"""

    # only valid users
    if request.user_id not in {0, 1, 2, 3, 4, 5}:
      context.abort(grpc.StatusCode.NOT_FOUND, "User not found")

    # the lists of results
    detected_objects = list()
    detected_faces = list()
    detected_yolos = list()

    # write the frame into the local visualization queue
    global jpegbuffer
    global lastjpegtime
    jpegbuffer = request.frame.img
    lastjpegtime = time.time()

    # sequential or parallel sub-request
    if args.parallel:

      # prepare requests
      if request.wantface:
        facerequest = FaceDetectionRequest(max_results=request.max_results, frame=request.frame)
      if request.wantyolo:
        yolorequest = YoloDetectionRequest(max_results=request.max_results, frame=request.frame)

      # expect responses as futures (nonblocking)
      if request.wantface:
        facedetresponse_future = faceclient.FaceDetect.future(facerequest)
      if request.wantyolo:
        yolodetresponse_future = yoloclient.YoloDetect.future(yolorequest)

      # join on the executed futures (blocking)
      if request.wantface:
        facedetresponse = facedetresponse_future.result()
      if request.wantyolo:
        yolodetresponse = yolodetresponse_future.result()

      # prepare the lists
      if request.wantface:
        for face in facedetresponse.faces:
          if len(detected_faces) < request.max_results:
            detected_faces.append(DetectedObject(name="face", eng=0, confidence=face.confidence, x=face.x, y=face.y, w=face.w, h=face.h, r=face.r, g=face.g, b=face.b))
          else:
            break
      if request.wantyolo:
        for yolo in yolodetresponse.yolos:
          if len(detected_yolos) < request.max_results:
            detected_yolos.append(DetectedObject(name=yolo.name, eng=1, confidence=yolo.confidence, x=yolo.x, y=yolo.y, w=yolo.w, h=yolo.h, r=yolo.r, g=yolo.g, b=yolo.b))
          else:
            break

    else:

      # perform a blocking call to the face detector
      if request.wantface:
        detected_faces = self.FaceDetectCall(request)
     
      # perform a blocking call to the yolo detector
      if request.wantyolo:
        detected_yolos = self.YoloDetectCall(request)

    # merge results
    detected_objects.extend(detected_faces)
    detected_objects.extend(detected_yolos)
    
    return ObjectDetectionResponse(number=request.frame.number, timestamp=request.frame.timestamp, objects=detected_objects, ipv4=hostipv4, name=hostname)


def serveGRPC():
  """GRPC serving function"""

  # define the server
  global GRPCserver
  GRPCserver = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

  # add a service
  detection_pb2_grpc.add_ObjectDetectionServicer_to_server(ObjectDetectionService(), GRPCserver)

  # open a port on all interfaces
  GRPCserver.add_insecure_port("[::]:50051")

  # start serving
  GRPCserver.start()

  # start the server
  print("Object server started")
  GRPCserver.wait_for_termination()
  print("Object server stopped")

class MJPEGServerThread(threading.Thread):

  def __init__(self, app):
    threading.Thread.__init__(self)
    self.server = make_server('0.0.0.0', 8088, app)
    self.ctx = app.app_context()
    self.ctx.push()

  def run(self):
    print('MJPEG server started')
    self.server.serve_forever()
    print('MJPEG server stopped')

  def shutdown(self):
    self.server.shutdown()

def relay():
  global keepRunning
  global lastjpegtime
  global jpegbuffer
  global pausedjpegbuffer
  while keepRunning:
    agetime = time.time() - lastjpegtime
    if agetime > 2:
      jpegbuffer = pausedjpegbuffer
      lastjpegtime = time.time()
    else:
      yield memoryview(jpegbuffer)
    time.sleep(0.020)

def startMJPEGserver():
  global keepRunning
  keepRunning = True
  global MJPEGserver
  app = Flask('myapp')

  @app.route('/')
  def stream():
    return MJPEGResponse(relay())  
  
  MJPEGserver = MJPEGServerThread(app)
  MJPEGserver.start()

def stopMJPEGserver():
  global MJPEGserver
  global keepRunning
  keepRunning = False
  MJPEGserver.shutdown()


def handle_sigs(*_):
  """Handle OS signals for shutdown etc."""

  print("Received shutdown signal, doing gracefully")
  # ask the server to stop in a reasonable amount of time, and wait for it
  all_rpcs_done_event = GRPCserver.stop(30)
  all_rpcs_done_event.wait(30)


if __name__ == "__main__":
  """Go!"""

  # register a couple of signals we are interested in
  signal(SIGTERM, handle_sigs)
  signal(SIGINT, handle_sigs)
  
  if args.webserve:
    startMJPEGserver()
  serveGRPC()
  if args.webserve:
    stopMJPEGserver()