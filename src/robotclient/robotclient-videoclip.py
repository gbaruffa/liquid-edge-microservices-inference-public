# imports
import grpc
import cv2
import os
import argparse
import signal
import sys
import time
import datetime
from detection_pb2_grpc import ObjectDetectionStub
from detection_pb2 import ObjectDetectionRequest, VideoFrame
import math
import threading
from robomaster import version as rmversion, robot as rmrobot, led as rmled, blaster as rmblaster
from flask import Flask
from mjpeg.server import MJPEGResponse
from werkzeug.serving import make_server
from kbhit import KBHit

# Capture CTRL-C
def handler(signum, frame):
  global processing
  processing = False


# clip a value
def clamp(val, smallest, largest, precision): 
  """Limits val between smallest and largest, and outputs zero if abs(val) is less than precision"""
  return 0 if math.fabs(val) < precision else max(smallest, min(val, largest))


# exec blocking actions in a separate thread
eprobot_sound_lock = threading.Lock()
def eprobot_action_thread(act, epr: rmrobot.Robot):
  if act == "unrecognized":
    epr.led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=255, b=0, effect=rmled.EFFECT_OFF, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
    eprobot_sound_lock.acquire()
    epr.play_sound(rmrobot.SOUND_ID_1F).wait_for_completed()
    eprobot_sound_lock.release()
  elif act == "recognized":
    epr.led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=255, b=0, effect=rmled.EFFECT_ON, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
    eprobot_sound_lock.acquire()
    #epr.gimbal.recenter().wait_for_completed()
    epr.play_sound(rmrobot.SOUND_ID_1A).wait_for_completed()
    eprobot_sound_lock.release()


global jpegbuffer
dir_path = os.path.dirname(os.path.realpath(__file__))
with open(dir_path + "/liquid_edge_paused.jpg", mode='rb') as file: # b is important -> binary
  jpegbuffer = file.read()
global pausedjpegbuffer
pausedjpegbuffer = jpegbuffer
global lastjpegtime
lastjpegtime = time.time()

class MJPEGServerThread(threading.Thread):

  def __init__(self, app):
    threading.Thread.__init__(self)
    self.server = make_server('0.0.0.0', 9088, app)
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


# hit management
washit = 0
hitpos = -1
def hit_callback(sub_info, epr: rmrobot.Robot):
  armor_id, hit_type = sub_info
  global washit
  washit = cv2.getTickCount()
  #armor_id = hitpos
  print("hit event: hit_comp:{0}, hit_type:{1}".format(armor_id, hit_type))

print(datetime.datetime.now())
print("openCV version:", cv2.__version__)
print("python version:", sys.version)
print("grpcio version:", grpc.__version__)

# parse arguments
parser = argparse.ArgumentParser(description="Robot client")
parser.add_argument("-s", "--speed", help="Full speed, no detection", action="store_true", dest="speed", default=None)
parser.add_argument("-c", "--control", help="Enable controller",default=None, nargs='?', const='arg_was_not_given', dest="control", type=str)
parser.add_argument("-r", "--repeat", help="Repeat video clip", action="store_true", dest="repeat", default=None)
parser.add_argument("-0", "--zeroout", help="No screen output", action="store_true", dest="zeroout", default=None)
parser.add_argument("-k", "--track-objects", help="Track objects", action="store_true", dest="trackobj", default=None)
parser.add_argument("-j", "--dji-robomaster", help="Pilot DJI robomaster", action="store_true", dest="dji", default=None)
parser.add_argument("-n", "--novideo", help="Do not show video", action="store_true", dest="novideo", default=None)
#parser.add_argument("-i", "--input", help="Enter camera number or a file path", default="../liquid-edge-model-zoo/clips/londontraffic_854x480.mp4", dest="input")
parser.add_argument("-i", "--input", help="Enter camera number or a file path", default="../liquid-edge-model-zoo/clips/manhattanwalk_854x480.mp4", dest="input")
#parser.add_argument("-i", "--input", help="Enter camera number or a file path", default="../liquid-edge-model-zoo/clips/trainer_480p.mp4", dest="input")
parser.add_argument("-a", "--alpha", help="FPS averaging constant", default="0.97", dest="alpha", type=float)
parser.add_argument("-o", "--max-objects", help="Number of max. reported objects", default="10", dest="objects", type=int)
parser.add_argument("-t", "--object-type", help="Type of object to track", default="face", dest="objecttype", type=str)
parser.add_argument("-l", "--log-file", help="Log results to file", action="store_true", dest="logfile", default=None)
parser.add_argument("-w", "--web-serve", help="Web server for camera viewing on port 9088", default=False, action='store_true', dest='webserve')
parser.add_argument("-V", "--version", action="version", version="0.1")
parser.add_argument("address", help="Server address:port", default="localhost:50051", nargs="?")
args = parser.parse_args()

# open communication channel
objectdetection_host = os.getenv("OBJECTDETECTION_HOST", args.address)
objectdetection_channel = grpc.insecure_channel(objectdetection_host)
client = ObjectDetectionStub(objectdetection_channel)

# availableBackends = [cv2.videoio_registry.getBackendName(b) for b in cv2.videoio_registry.getBackends()]
# print(availableBackends)

# open video capture
if args.input.isnumeric():
  #if not args.dji:
  print("Opening camera")
  cap = cv2.VideoCapture(int(args.input), cv2.CAP_V4L2)
  if cap.isOpened() is False:
    print("Error opening video stream")
    exit()
  cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
  cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
  #cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
  cap.set(cv2.CAP_PROP_FPS, 30)
  #cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
  print(cap.get(cv2.CAP_PROP_FRAME_WIDTH), "x", cap.get(cv2.CAP_PROP_FRAME_HEIGHT), "@", cap.get(cv2.CAP_PROP_FPS), "EXP", cap.get(cv2.CAP_PROP_AUTO_EXPOSURE))
else:
  print("Opening file: " + args.input)
  cap = cv2.VideoCapture(args.input)
  if cap.isOpened() is False:
    print("Error opening file")
    exit()
    
#open video display
if args.novideo:
  display = None
else:
  if os.name == "nt":
    """Windows client"""
    display = True
  else:
    """X client"""
    display = os.getenv("DISPLAY")

# general initializations
total_num_frames = 0
total_time = cv2.getTickCount() / cv2.getTickFrequency()
total_rtt = 0
prev_frame_time = 0
new_frame_time = 0
fps = 0
rtt = 0
font = cv2.FONT_HERSHEY_PLAIN
width = 0
height = 0
ipv4_previous = None
regobjects_previous = list()
winshown = False

# initialize log file
lf = None
if args.logfile:
  try:
    lf = open("logfile.csv", 'w')
    lf.write('"framenum","rtt","objnum","time","interface"\n')
  except:
    pass

# initialize our centroid tracker
if args.trackobj:
  from objecttracker import ObjectTracker
  ot = ObjectTracker()

# initialize PID controllers
if args.control:
  from simple_pid import PID
  if args.control == 'arg_was_not_given':
    #pidks = (-1,-0.1,-0.05,1,0.0,0.0) # Tommaso's
    pidks = (-1.5,-0.1,-0.05,4.5,0.0,0.0)
  else:
    pidks = list(map(float, args.control.split(',')))
  print(pidks)
  if args.trackobj is None:
    print("Tracking must be enabled for the controller to work")
    exit()
  # left-right and forw-backw controllers PID(Kp: float, Ki: float, Kd: float, ...)
  pid_lr = PID(pidks[0], pidks[1], pidks[2], output_limits=(-1000, +1000), sample_time=0.1)
  pid_fb = PID(pidks[3], pidks[4], pidks[5], output_limits=(-1000, +1000), sample_time=0.1)

# connect with the  DJI Robomaster
if args.dji:
  if args.control is None:
    print("Controller must be enabled for DJI robot piloting to work")
    exit()
  wasunrecognized = True
  wasrecognized = False
  try:
    print("DJI SDK version:", rmversion.__version__)
    ep_robot = rmrobot.Robot()
    ep_robot.initialize(conn_type="rndis")
    ep_robot.set_robot_mode(mode='chassis_lead') 
    ep_chassis = ep_robot.chassis
    #ep_robot.gimbal.recenter().wait_for_completed()
   # ep_camera = ep_robot.camera
   # ep_camera.start_video_stream(display=False, resolution='720p') # 360p, 540p, 720p
    ep_armor = ep_robot.armor
    ep_armor.set_hit_sensitivity(comp="all", sensitivity=1)
    ep_armor.sub_hit_event(hit_callback, ep_robot)
    print("DJI robot version: {0}".format(ep_robot.get_version()))
  except:
    print("DJI Robomaster robot not found")
    exit()
  ep_led = ep_robot.led
  ep_led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, effect=rmled.EFFECT_OFF)

# associate CTRL-C to handler
#signal.signal(signal.SIGINT, handler)

# prepare the window
if not args.novideo:
  cv2.namedWindow("Detection results", cv2.WINDOW_NORMAL) 
  winshown = False

# embedded web server for debugging
if args.webserve:
  startMJPEGserver()

# prepare for receiving keyboard presses
kb = KBHit()

# infinite loop
last_pid_error_lr = 0
selected_object_id = None
processing = True
manual_mode = False
while processing:

  # capture the image
  # if args.dji:
  #"""from the robot"""
  # img = ep_camera.read_cv2_image(timeout=1, strategy='newest')
  #frmnum = 0
  #else:
  """from the camera or a file"""
  ret, img = cap.read()
  frmnum = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
  if not ret:
    if args.repeat:
      """Restarts the video since it is probably ended"""
      cap = cv2.VideoCapture(args.input)
      ret, img = cap.read()
      if not ret:
        """Uhm, some other problem"""
        print("Problem reading from input")
        exit()
    else:
      """Uhm, some other problem"""
      print("Problem reading from input")
      break
      
  # recalc center
  if img.shape[1] != width:
    height = img.shape[0]
    width = img.shape[1]
    if args.control:
      pid_lr.setpoint = 0.5 * width
      pid_fb.setpoint = 0.8 * height

  # compress a video frame
  #cv2.imwrite('image1.jpg',img)
  cfrm = VideoFrame(number=frmnum, timestamp=cv2.getTickCount(), img=cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 98])[1].tobytes())

  # prepare a gRPC request
  detrequest = ObjectDetectionRequest(user_id=1, max_results=args.objects, frame=cfrm, wantface=not args.speed, wantyolo=not args.speed)

  # call the RPC
  try:
    detresponse = client.ObjectDetect(detrequest, timeout=1)
    #print('r')
  except Exception as e: 
    #print(e)
    detresponse = None

	# update our centroid tracker using the computed set of bounding box rectangles
  if args.trackobj:

    if detresponse:
      regobjects = ot.update(detresponse.objects)
      regobjects_previous = regobjects
    else:
      #regobjects = list()
      regobjects = regobjects_previous

    selected_regidx = None
    if selected_object_id is None:
      # select the largest object
      object_area = 0
      for ridx, regobject in enumerate(regobjects):
        if regobject.name == args.objecttype and regobject.width * regobject.height > object_area:
          object_area = regobject.width * regobject.height
          selected_object_id = regobject.oid
          selected_regidx = ridx
    else:
      # find the selected object
      for ridx, regobject in enumerate(regobjects):
        if regobject.oid == selected_object_id:
          selected_regidx = ridx
          break
      if selected_regidx is None:
        selected_object_id = None

  # get keypresses
  delta_fb = 0
  delta_lr = 0
  if kb.kbhit():
    c = kb.getch()
    #print("pressed", ord(c), ' ')
    if c == 'w':
      delta_fb = 150
    elif c == 'z':
      delta_fb = -150
    elif c == 'a':
      delta_lr = -150
    elif c == 's':
      delta_lr = 150
    elif c == 'm':
      manual_mode = not manual_mode
      print("MANUAL MODE", manual_mode)
    elif c == 'r':
      print("RESETTING!")
      if args.control:
        pid_fb.reset()
        pid_lr.reset()
        if args.dji:
          ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)

  # use the controller on the selected object
  if args.control:

    """Update the PIDs"""
    if selected_regidx is not None:
      if regobjects[selected_regidx].height > regobjects[selected_regidx].width:
        pid_fb.setpoint = 0.8 * height
      else:
        pid_fb.setpoint = 0.4 * height
      pid_output_lr = pid_lr(regobjects[selected_regidx].cx)
      pid_output_fb = pid_fb(regobjects[selected_regidx].height)
      pid_error_lr = pid_lr.setpoint - regobjects[selected_regidx].cx
      # integral term windup correction
      if pid_error_lr * last_pid_error_lr < 0:
        pid_lr.reset()
        last_pid_error_lr = 0
      last_pid_error_lr = pid_error_lr
        
    else:
      pid_lr.reset()
      pid_fb.reset()    
      pid_output_lr = None
      pid_output_fb = None 

    if manual_mode:
      pid_output_fb = delta_fb
      pid_output_lr = delta_lr

  # simple random number generator
  def lcg(x, a, c, m):
    return (a * x + c) % m

  # pilot the DJI
  if args.dji:
    if detresponse:
      #print(detresponse.ipv4)
      ipv4 = int(detresponse.ipv4)
    else:
      ipv4 = 0
    if ipv4 != ipv4_previous and ipv4 != 0:
      a, c, m = 1103515245, 12345, 0xffffffff
      bsdrand = lcg(ipv4, a, c, m)
      #ipv4_list = [int(x) for x in str(ipv4)]
      #ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=(int("".join(map(str, ipv4_list[33:36]))))&0x00ff, g=(int("".join(map(str, ipv4_list[29:32]))))&0x00ff, b=(int("".join(map(str, ipv4_list[5:7]))))&0x00ff, effect=rmled.EFFECT_ON)
      ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=bsdrand&0x000000ff, g=(bsdrand>>8)&0x000000ff, b=(bsdrand>>16)&0x000000ff, effect=rmled.EFFECT_ON)
      ipv4_previous = ipv4

    #print(ipv4)
    if selected_regidx is None:

      # no object recognized
      if wasrecognized:
        # we just lost it, play a bell
        threading.Thread(target=eprobot_action_thread, args=("unrecognized", ep_robot)).start()
        # stop motion
        ep_chassis.drive_speed(x=0, y=0, z=0, timeout=10)
        wasrecognized = False

      # make a rotation till we find it again
      wasunrecognized = True
      fb_speed = 0
      lr_speed = 0
      #ep_chassis.drive_speed(x=0, y=0, z=-6)
      #ep_chassis.drive_speed(x=0, y=0, z=math.copysign(16, lr_speed)) # Tommaso's
      if not manual_mode:
        ep_chassis.drive_speed(x=0, y=0, z=math.copysign(24, lr_speed))
      else:
        ep_chassis.drive_speed(x=0, y=0, z=0)
        #ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)

    else:

      # the object is recognized
      ep_led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=255 - regobjects[selected_regidx].missing*5, b=0, effect=rmled.EFFECT_ON, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
      if wasunrecognized:
        # we just acquired it, play a bell
        threading.Thread(target=eprobot_action_thread, args=("recognized", ep_robot)).start()
        wasunrecognized = False

      # follow the object actively
      wasrecognized = True
      fb_scale = 1/1000
      lr_scale = 1/10
      #fb_absmax = 0.2 #Tommaso's
      #fb_absmax = 1.0 #mine
      fb_absmax = 0.6
      fb_absmin = 0.09
      #lr_absmax = 15 # Tommaso's
      lr_absmax = 20
      lr_absmin = 1
      fb_speed = clamp((pid_output_fb)*fb_scale, -fb_absmax, fb_absmax, fb_absmin)
      lr_speed = clamp((pid_output_lr)*lr_scale, -lr_absmax, lr_absmax, lr_absmin)
      # if lr_speed == 0:
      #   ep_robot.blaster.set_led(brightness=255, effect=rmblaster.LED_ON)
      # else:
      #   ep_robot.blaster.set_led(brightness=0, effect=rmblaster.LED_OFF)
      if fb_speed == 0 and lr_speed == 0:
        ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)
      else:
        ep_chassis.drive_speed(x=fb_speed, y=0, z=lr_speed, timeout=0)

  # time when we finish processing for this frame
  new_frame_time = cv2.getTickCount() / cv2.getTickFrequency()

  # Calculating the fps
  total_num_frames = total_num_frames + 1
  inst_fps = 1 / (new_frame_time - prev_frame_time)
  fps = args.alpha * fps + (1 - args.alpha) * inst_fps  # IIR-filtered fps
  prev_frame_time = new_frame_time
  with open("/tmp/currentovsport","r") as f:
      ovsport = f.read().rstrip()
  if detresponse:
    inst_rtt = 1000 * (cv2.getTickCount() - detresponse.timestamp) / cv2.getTickFrequency()
    if lf:
      lf.write("%d,%f,%d,%f,%s\n" % (total_num_frames, inst_rtt, len(detresponse.objects), time.time(), ovsport))
    total_rtt += inst_rtt
    """IIR-filtered rtt"""
    rtt = args.alpha * rtt + (1 - args.alpha) * inst_rtt
    if not args.zeroout:
      if args.control and pid_output_lr is not None:
        print(f"{ovsport},dobjs={len(detresponse.objects)},tobjs={len(regobjects)},LR={pid_output_lr:.1f},FB={pid_output_fb:.1f},rtt={rtt:.0f},fps={fps:.1f} 📶        ", end="\r", flush=True)
      elif args.trackobj:
        print(f"{ovsport},dobjs={len(detresponse.objects)},tobjs={len(regobjects)},rtt={rtt:.0f},fps={fps:.1f} 📶        ", end="\r", flush=True)
      else:
        print(f"{ovsport},dobjs={len(detresponse.objects)},rtt={rtt:.0f},fps={fps:.1f} 📶        ", end="\r", flush=True)
  else:
    if lf:
      lf.write("%d,%f,%d,%f,%s\n" % (total_num_frames, math.nan, 0, time.time(), ovsport))
    print(ovsport + ",NO LINK 📴                     ", end="\r", flush=True)


  # display the processed image
  if display or args.webserve:

    # loop over the tracked objects
    if args.trackobj:
      for ridx, regobject in enumerate(regobjects):
        # the color is initially vivid, then it washes out
        color = (0, 0, 255 - regobject.missing*5) if ridx == selected_regidx else (255 - regobject.missing*5, 0, 0)
        #color = regobject.color
        thickness = 2 if ridx == selected_regidx else 1
        # a rectangle encloses the object
        cv2.rectangle(img, (int(regobject.cx - regobject.width/2), int(regobject.cy - regobject.height/2)), (int(regobject.cx + regobject.width/2), int(regobject.cy + regobject.height/2)), color, thickness)
        # a cross indicates the centroid
        cv2.line(img, (int(regobject.cx - 3), int(regobject.cy - 3)), (int(regobject.cx + 3), int(regobject.cy + 3)), [255 - color[0], 255 - color[1], 255 - color[2]], thickness)
        cv2.line(img, (int(regobject.cx - 3), int(regobject.cy + 3)), (int(regobject.cx + 3), int(regobject.cy - 3)), [255 - color[0], 255 - color[1], 255 - color[2]], thickness)
        # a descriptor
        cv2.putText(img, f"{regobject.oid}: {regobject.name}", (int(regobject.cx - regobject.width/2), int(regobject.cy - regobject.height/2 - 3)), font, 0.6, color, 1)

    elif detresponse:

      # loop over the detected objects
      for didx, detobject in enumerate(detresponse.objects):
        color = (0, 255, 0) 
        # a rectangle encloses the object
        cv2.rectangle(img, (detobject.x, detobject.y), (detobject.x + detobject.w, detobject.y + detobject.h), color, 1)
        # a tiny descriptor
        cv2.putText(img, f"{didx}: {detobject.name}", (detobject.x, detobject.y - 3), font, 0.6, color, 1)

    # print control values
    if args.control:
      """Textual info"""
      if pid_output_lr:
        cv2.putText(img, f"LR:{pid_output_lr:.1f}", (10, height - 35), font, 2, (0, 0, 255), 2)
      else:
        cv2.putText(img, "LR:---", (10, height - 35), font, 2, (0, 0, 255), 2)
      if pid_output_fb:
        cv2.putText(img, f"FB:{pid_output_fb:.1f}", (10, height - 10), font, 2, (0, 0, 255), 2)
      else:
        cv2.putText(img, "FB:---", (10, height - 10), font, 2, (0, 0, 255), 2)
      if args.dji:
        cv2.putText(img, f"x:{lr_speed:.2f}", (width-120, height - 35), font, 2, (0, 0, 255), 2)
        cv2.putText(img, f"y:{fb_speed:.2f}", (width-120, height - 10), font, 2, (0, 0, 255), 2)
        if (cv2.getTickCount() - washit) / cv2.getTickFrequency() < 0.5:
          cv2.rectangle(img, (0, 0), (width - 1, height - 1), (255, 255, 255), 3)
          #if hitpos == 0:
          #  cv2.line(img, (0, 0), (width - 1, 0), (255, 255, 255), 3)

      """Graphical info"""
      try:
        output_abs = math.sqrt(pid_output_lr**2 + pid_output_fb**2)
      except:
        output_abs = 0
      try:
        output_ang = math.atan2(pid_output_fb, pid_output_lr)
      except:
        output_ang = 0
      arw_center = (int(width/2), int(height/2))
      arw_tip = (int(arw_center[0] + output_abs*math.cos(output_ang)), int(arw_center[1] - output_abs*math.sin(output_ang)))
      cv2.arrowedLine(img, arw_center, arw_tip, (0, 0, 255), 2, 8, 0, 0.1)
      cv2.putText(img, f"{inst_rtt:.0f}ms", (10, 35), font, 2, (0, 255, 0), 2)
    
    #cv2.imwrite('image1.png',img)

    # show in the X11 window
    if display:
      cv2.imshow("Detection results", img)

      # Bugfix: sometimes the window is clipped at startup
      if not winshown:
        cv2.resizeWindow("Detection results", width, height)
        winshown = True

    # write the frame into the local visualization queue
    if args.webserve:
      jpegbuffer = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 98])[1].tobytes()
      lastjpegtime = time.time()

  # go out with ESC
  keycode = cv2.waitKey(1) & 255
  if keycode == 27:
    break
  elif keycode == 32:
    time.sleep(5)
  elif keycode == 114: # 'r'
    print("RESETTING!")
    if args.control:
      pid_fb.reset()
      pid_lr.reset()
      if args.dji:
        ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)

# print digest
total_time = cv2.getTickCount() / cv2.getTickFrequency() - total_time
print(f"Total frames: {total_num_frames}; avg. fps: {total_num_frames / total_time:.1f}; avg. rtt: {total_rtt / total_num_frames:.1f}")
if lf:
  lf.close()

# reset keyboard acquisition
kb.set_normal_term()

# close serving the image
if args.webserve:
  stopMJPEGserver()

# when everything is done, release the capture
if not args.dji:
  cap.release()

# destroy all windows now
cv2.destroyAllWindows()

# close the robot
if args.dji:
  ep_led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=0, b=0, effect=rmled.EFFECT_OFF, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
  ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, g=0, r=0, b=0, effect=rmled.EFFECT_OFF)
  ep_camera.stop_video_stream()
  ep_armor.unsub_hit_event()
  ep_robot.close()
