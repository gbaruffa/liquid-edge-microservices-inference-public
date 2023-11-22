from concurrent import futures
from inspect import CORO_CLOSED
import grpc
from detection_pb2 import (DetectedFace, FaceDetectionResponse)
import detection_pb2_grpc
import cv2
import numpy as np
from signal import signal, SIGTERM, SIGINT
import sys

print("openCV version:", cv2.__version__)
print("python version:", sys.version)
print("grpcio version:", grpc.__version__)


class FaceDetectionService(detection_pb2_grpc.FaceDetectionServicer):
  """This service class is devoted to face detection"""

  # prepare face classifier
  try:
    faceCascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
  except:
    faceCascade = cv2.CascadeClassifier("/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml")

  def FaceDetect(self, request, context):
    """This method detects the faces in the received frame"""

    # decompress image
    img = cv2.imdecode(np.frombuffer(request.frame.img, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    # print(f"size:{img.shape[1]}x{img.shape[0]}")

    # convert to gray scale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # print(f"size:{gray.shape[1]}x{gray.shape[0]}")

    # detect faces
    faces = self.faceCascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=3, minSize=(30, 30))
    #print(f"Found {len(faces)} Faces!")

    # limit the number of reported results
    num_results = min(request.max_results, len(faces))

    # prepare detected objects array
    detected_faces = []
    nr = 0
    for (x, y, w, h) in faces:
      if nr < num_results:
        if w > 0 and h > 0:
          # average color of the centroid
          #ccolor = np.average(np.average(img[int(y - h/2 - 2):int(y + h/2 + 2), int(x - w/2 - 2):int(x + w/2 + 2)], axis=0), axis=0)
          ccolor = [0, 0, 255]
          detected_faces.append(DetectedFace(confidence=1, x=x, y=y, w=w, h=h, r=int(ccolor[2]), g=int(ccolor[1]), b=int(ccolor[0])))
          nr += 1
      else:
        break

    #time.sleep(1)
    return FaceDetectionResponse(number=request.frame.number, timestamp=request.frame.timestamp, faces=detected_faces)


def serve():
  """Serving function"""
  server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
  detection_pb2_grpc.add_FaceDetectionServicer_to_server(FaceDetectionService(), server)
  server.add_insecure_port("[::]:50053")
  server.start()

  def handle_sigs(*_):
    print("Received shutdown signal, doing gracefully")
    all_rpcs_done_event = server.stop(30)
    all_rpcs_done_event.wait(30)

  signal(SIGTERM, handle_sigs)
  signal(SIGINT, handle_sigs)
  print("Face server started")
  server.wait_for_termination()


if __name__ == "__main__":
  """Go!"""
  serve()
