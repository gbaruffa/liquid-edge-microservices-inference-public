###########
# imports #
###########
import argparse
import cv2
import datetime
from detection_pb2_grpc import ObjectDetectionStub
from detection_pb2 import ObjectDetectionRequest, VideoFrame
from enum import Enum
import flask
import grpc
import kbhit
import math
import mjpeg.server
import numpy as np
import os
from picamera2 import Picamera2
import random
from robomaster import version as rmversion, robot as rmrobot, led as rmled, blaster as rmblaster
import signal
import sys
import threading
import time
import werkzeug.serving


####################
# Global variables #
####################
global processing
processing = True
global rgb_triple
rgb_triple = (64, 64, 64)


##################
# Capture CTRL-C #
##################
def sighandler(signum, frame):
  global processing
  processing = False


###################
# Object tracking #
###################
class Object():
  """The basic tracked object"""

  def __init__(self, cx, cy, w, h, name, clr=[0,0,0]):
    self.cx = cx
    self.cy = cy
    self.width = w
    self.height = h
    self.name = name
    self.missing = 0
    self.color = clr
    self.oid = None


class ObjectTracker():
  """Class used to track some objects"""

  #def __init__(self, maxMissing: int = 5):
  def __init__(self, maxMissing: int = 25):
    # initialize the next unique object ID along with the list of registered o.
    self.nextRegObjectID = 0
    self.trackobjects: list(Object) = []

		# number of maximum consecutive frames a given object is allowed to be marked as "missing" until we need to deregister it from tracking
    self.maxMissing = maxMissing


  def register(self, object: Object):
    # when registering an object we use the next available object ID to store it
    object.oid = self.nextRegObjectID
    self.trackobjects.append(object)
    self.nextRegObjectID += 1


  def update(self, det_objects):
    # # arrays of centroid colors
    # detcolors = [[0, 0, 0]]*len(detobjects)
    # for didx, detobject in enumerate(detobjects):
    #   average_color_row = np.average(img[int(detobject.y + detobject.h/2) - 2:int(detobject.y + detobject.h/2) + 2, int(detobject.x + detobject.w/2) - 2:int(detobject.x + detobject.w/2) + 2], axis=0)
    #   detcolors[didx] = np.average(average_color_row, axis=0)
    #   #detcolors[didx] = img[int(detobject.y + detobject.h/2), int(detobject.x + detobject.w/2)]       
      
    # in case there are no registered objects, create them and go out
    if len(self.trackobjects) == 0:
      for didx, det_object in enumerate(det_objects):
        self.register(Object(det_object.x + det_object.w/2, det_object.y + det_object.h/2, det_object.w, det_object.h, det_object.name, [det_object.b, det_object.g, det_object.r]))
      return self.trackobjects
      
    # array of mutual distances: rows are registered o., columns are detected o., name of o. is verified
    MyMetrics = [[math.inf for i in range(len(det_objects))] for j in range(len(self.trackobjects))]
    regchosens = [False]*len(self.trackobjects)
    detchosens = [False]*len(det_objects)
    alpha = 0.999 # memory of new detection
    for tidx, trackobject in enumerate(self.trackobjects):
      for didx, det_object in enumerate(det_objects):
        if trackobject.name == det_object.name:
          colorMetric = (float(trackobject.color[0]) - float(det_object.b))**2 + (float(trackobject.color[1]) - float(det_object.g))**2 + (float(trackobject.color[2]) - float(det_object.r))**2
          distMetric = (trackobject.cx - (det_object.x + det_object.w/2))**2 + (trackobject.cy - (det_object.y + det_object.h/2))**2
          MyMetrics[tidx][didx] = (1-alpha)*colorMetric/195075 + alpha*distMetric/1566976
          # MyMetrics[tidx][didx] = math.sqrt((trackobject.cx - (detobject.x + detobject.w/2))**2 + (trackobject.cy - (detobject.y + detobject.h/2))**2)
          # MyMetrics[tidx][didx] = ((trackobject.cx - trackobject.width/2) - detobject.x)**2 + ((trackobject.cy - trackobject.height/2) - detobject.y)**2 
          # + ((trackobject.cx + trackobject.width/2) - detobject.x - detobject.w)**2 + ((trackobject.cy + trackobject.height/2) - detobject.y)**2 
          # + ((trackobject.cx - trackobject.width/2) - detobject.x)**2 + ((trackobject.cy + trackobject.height/2) - detobject.y - detobject.h)**2 
          # + ((trackobject.cx + trackobject.width/2) - detobject.x - detobject.w)**2 + ((trackobject.cy + trackobject.height/2) - detobject.y - detobject.h)**2

    # find the registered o. nearest to a detected o.
    for didx, det_object in enumerate(det_objects):
      if not detchosens[didx]:
        ridxmin = None
        distmin = math.inf
        for tidx, trackobject in enumerate(self.trackobjects):
          if not regchosens[tidx] and MyMetrics[tidx][didx] < distmin:
            distmin = MyMetrics[tidx][didx]
            ridxmin = tidx
        if distmin < math.inf:    
          # verify it is the smallest horizontally
          smallest = True
          for didx2 in range(len(det_objects)):
            if not detchosens[didx2] and MyMetrics[ridxmin][didx2] < distmin:
              smallest = False
              break
          # update registered
          if smallest:
            beta = 0.5 # IIR filtering constant
            self.trackobjects[ridxmin].cx = beta*self.trackobjects[ridxmin].cx + (1 - beta)*(det_objects[didx].x + det_objects[didx].w/2)
            self.trackobjects[ridxmin].cy = beta*self.trackobjects[ridxmin].cy + (1 - beta)*(det_objects[didx].y + det_objects[didx].h/2)
            self.trackobjects[ridxmin].width = beta*self.trackobjects[ridxmin].width + (1 - beta)*det_objects[didx].w
            self.trackobjects[ridxmin].height = beta*self.trackobjects[ridxmin].height + (1 - beta)*det_objects[didx].h
            self.trackobjects[ridxmin].missing = 0
            self.trackobjects[ridxmin].color[0] = beta*self.trackobjects[ridxmin].color[0] + (1 - beta)*det_object.b
            self.trackobjects[ridxmin].color[1] = beta*self.trackobjects[ridxmin].color[1] + (1 - beta)*det_object.g
            self.trackobjects[ridxmin].color[2] = beta*self.trackobjects[ridxmin].color[2] + (1 - beta)*det_object.r
            # mark the pairing as done
            regchosens[ridxmin] = True
            detchosens[didx] = True

    # control missing registered o.
    for tidx, trackobject in enumerate(self.trackobjects):
      if not regchosens[tidx]:
        trackobject.missing += 1

    # purge old missing registered o.
    self.trackobjects[:] = [trackobject for trackobject in self.trackobjects if trackobject.missing < self.maxMissing]

    # insert new detected o.
    for didx, det_object in enumerate(det_objects):
      if not detchosens[didx]:
        self.register(Object(det_object.x + det_object.w/2, det_object.y + det_object.h/2, det_object.w, det_object.h, det_object.name, [det_object.b, det_object.g, det_object.r]))

    return self.trackobjects


#####################
# navigation thread #
#####################
def navi_thread(a):

  global processing
  global last_postick
  global robot_pos
  global robot_vel
  global pathimg
  last_navitick = 1
  last_postick = 0
  robot_vel = [0,0,0,0,0,0]
  last_robopos = [0,0,0]
  
  print("navigation started")

  while processing:

    if last_postick > last_navitick:
      last_navitick = cv2.getTickCount()

      if pathimg is not None:
        xpix = int(robot_pos[0] * 80 + width/2)
        ypix = int(robot_pos[1] * 80 + height/2)
        if xpix >= 0 and xpix < width and ypix >= 0 and ypix < height:
          #print(xpix, ypix)
          pathimg[ypix][xpix] = [0, 0, 255, 128]

    time.sleep(0.025)

  print("navigation stopped")


###################
# tracking thread #
###################
def track_thread(a):

  # initialize our centroid tracker
  if a.trackobj:
    ot = ObjectTracker()
  else:
    return

  print("tracking started")

  global processing
  global det_response
  global last_dettick
  global trackobjects
  global selected_trackidx
  global width
  global height
  global e_lr
  global e_fb
  last_dettick = 0
  lasttracktick = 1
  det_response = None
  trackobjects_previous = list()
  selected_object_id = None
  while processing:

    # only when necessary
    if last_dettick > lasttracktick:

      # update the tracked objects list
      if det_response:
        trackobjects = ot.update(det_response.objects)
        trackobjects_previous = trackobjects
      else:
        trackobjects = trackobjects_previous

      # make a selection
      tmp_selected_trackidx = None
      if selected_object_id is None:
        # not following, select the largest object of the wanted type
        object_area = 0
        for tidx, trackobject in enumerate(trackobjects):
          if trackobject.name == a.objecttype and trackobject.width * trackobject.height > object_area:
            object_area = trackobject.width * trackobject.height
            selected_object_id = trackobject.oid
            tmp_selected_trackidx = tidx
      else:
        # already following, find the selected object
        for tidx, trackobject in enumerate(trackobjects):
          if trackobject.oid == selected_object_id:
            tmp_selected_trackidx = tidx
            break
        if tmp_selected_trackidx is None:
          selected_object_id = None
      selected_trackidx = tmp_selected_trackidx

      # control
      if a.control:
        if selected_trackidx is not None:
          e_lr = width/2 - trackobjects[selected_trackidx].cx
          #e_fb = height - trackobjects[selected_trackidx].height
          e_fb = trackobjects[selected_trackidx].width / width

      # update last time
      lasttracktick = cv2.getTickCount()

    # quick check
    time.sleep(0.01)
  
  print("tracking stopped")


#################
# status thread #
#################

# hit management
def hit_callback(sub_info, epr: rmrobot.Robot):
  global last_hittick
  global armor_id
  last_hittick = cv2.getTickCount()
  armor_id, hit_type = sub_info
  #print("hit event: armor_id:{0}, hit_type:{1}".format(armor_id, hit_type))

# status management
def sub_sta_handler(status_info):
  print(status_info)

# IMU management
def sub_imu_handler(imu_info):
  print(imu_info.acc_x)

# velocity management
def sub_vel_handler(velocity_info):
  global robot_vel
  global last_veltick
  robot_vel = velocity_info
  #print("CIAO", robot_vel[3:6])
  last_veltick = cv2.getTickCount()

# position management
def sub_pos_handler(position_info):
  global robot_pos
  global last_postick
  robot_pos = position_info
  last_postick = cv2.getTickCount()

# exec blocking actions in a separate thread
eprobot_sound_lock = threading.Lock()
def eprobot_action_thread(act, epr: rmrobot.Robot):
  if act == "unrecognized":
    #epr.led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=255, b=0, effect=rmled.EFFECT_OFF, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
    eprobot_sound_lock.acquire()
    epr.play_sound(rmrobot.SOUND_ID_1F).wait_for_completed()
    eprobot_sound_lock.release()
  elif act == "recognized":
    #epr.led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=255, b=0, effect=rmled.EFFECT_ON, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
    eprobot_sound_lock.acquire()
    epr.play_sound(rmrobot.SOUND_ID_1A).wait_for_completed()
    eprobot_sound_lock.release()

# the thread itself
def status_thread(a):

  print("status started")

  global status
  global last_tracktick
  global selected_trackidx
  global e_lr
  global e_fb
  global speed_x
  global speed_z
  global inst_rtt
  global last_hittick
  global armor_id
  global processing
  global has_robot
  global ep_led
  global forced_status
  global robot_vel
  global last_dettick
  global last_ledtick
  robot_vel = [0,0,0,0,0,0]
  has_robot = False
  forced_status = None
  last_hittick = 0
  inst_rtt = -1
  speed_x = 0
  speed_z = 0
  e_lr = 0
  e_fb = 0
  selected_trackidx = None
  last_tracktick = 0
  last_stattick = 1
  prev_status = ""
  status = "wakeup"
  search_timeout = 25
  last_changeticks = cv2.getTickFrequency()
  instatus_ticks = 0
  last_controltick = 0
  wakeup_timeout = 10

  # connect with the  DJI Robomaster
  if a.dji:
    if a.control is None:
      print("Controller must be enabled for DJI robot piloting to work")
      has_robot = False
      processing = False
    else:
      try:
        print("DJI SDK version:", rmversion.__version__)
        ep_robot = rmrobot.Robot()
        ep_robot.initialize(conn_type="rndis")
        ep_robot.set_robot_mode(mode='chassis_lead') 
        ep_chassis = ep_robot.chassis
        ep_armor = ep_robot.armor
        ep_armor.set_hit_sensitivity(comp="all", sensitivity=1)
        ep_led = ep_robot.led
        ep_led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, effect=rmled.EFFECT_OFF)
        ep_armor.set_hit_sensitivity(comp='all', sensitivity=0)
        ep_armor.sub_hit_event(hit_callback, ep_robot)
        ep_chassis.sub_position(freq=10, callback=sub_pos_handler)
        ep_chassis.sub_velocity(freq=10, callback=sub_vel_handler)
        #ep_chassis.sub_imu(freq=1, callback=sub_imu_handler)
        #ep_chassis.sub_status(freq=5, callback=sub_sta_handler)
        has_robot = True
        print("DJI robot version: {0}".format(ep_robot.get_version()))
      except:
        print("DJI Robomaster robot not found")
        has_robot = False
        processing = False

  # state machine
  last_searchledtick = 0
  last_followledtick = 0
  last_idleledtick = 0
  last_wakeupledtick = 0
  last_exploreledtick = 0
  while processing:

    # initial values
    speed_x = 0
    speed_y = 0
    speed_z = 0

    if status == "search":
      # search the object

      # we just lost the object
      if has_robot and prev_status != "search":
        # spin the robot around
        #ep_chassis.drive_speed(x=0, y=0, z=16*(1 if random.random() < 0.5 else -1))
        ep_chassis.drive_speed(x=0, y=0, z=24*(1 if e_lr < 0 else -1))
        # play the effects
        threading.Thread(target=eprobot_action_thread, args=("unrecognized", ep_robot)).start()

      # led effect
      if last_ledtick > last_searchledtick or prev_status != "search":
        ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=rgb_triple[0], g=rgb_triple[1], b=rgb_triple[2], effect=rmled.EFFECT_FLASH, freq=5)
        last_searchledtick = cv2.getTickCount()

      # check for timeout
      if instatus_ticks > search_timeout * cv2.getTickFrequency():
        new_status = "idle"
      else:
        # check if the object is no more present
        if selected_trackidx is not None:
          new_status = "follow"
        else:
          new_status = "search"

    elif status == "follow":
      # follow the object

      # we just acquired the object
      if has_robot and prev_status != "follow":
        # stop the robot
        ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)
        # play the effects
        threading.Thread(target=eprobot_action_thread, args=("recognized", ep_robot)).start()

      # led effect
      if last_ledtick > last_followledtick or prev_status != "follow":
        ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=rgb_triple[0], g=rgb_triple[1], b=rgb_triple[2], effect=rmled.EFFECT_ON, freq=1)
        last_followledtick = cv2.getTickCount()

      # check if the object is still present
      if selected_trackidx is None:
        # object not found
        new_status = "search"
      else:
        # object found
        new_status = "follow"
        # control
        if a.control and has_robot:
          # left/right
          if math.fabs(e_lr) < 5:
            speed_z = -0.06*e_lr
          else:
            speed_z = -0.16*e_lr # -math.copysign(max(0.05*e_lr,10),e_lr)

          # forward/backward
          ae_fb = math.fabs(e_fb)
          if ae_fb > 0.9:
            speed_x = -0.12
          elif ae_fb > 0.8:
            speed_x = -0.12
          elif ae_fb > 0.7:
            speed_x = -0.12
          elif ae_fb > 0.6:
            speed_x = -0.12
          elif ae_fb > 0.55:
            speed_x = 0
          elif ae_fb > 0.5:
            speed_x = 0.18
          elif ae_fb > 0.4:
            speed_x = 0.28
          elif ae_fb > 0.3:
            speed_x = 0.38
          elif ae_fb > 0.2:
            speed_x = 0.50
          elif ae_fb > 0.1:
            speed_x = 0.60
          else:
            speed_x = 0.60

          ep_chassis.drive_speed(x=speed_x, y=0, z=speed_z, timeout=0)
          last_controltick = cv2.getTickCount()

          # # got blocked
          # if math.sqrt(speed_x**2 + speed_y**2 + speed_z**2) > 10*robovel[3]:
          #   #print("BLOCKED!", math.sqrt(speed_x**2 + speed_y**2 + speed_z**2), robovel[3]/10)
          #   newstatus = "idle"
                  
    elif status == "idle":
      # idle state

      # stop the robot
      if has_robot and prev_status != "idle":
        ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)

      # led effect
      if last_ledtick > last_idleledtick or prev_status != "idle":
        ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=rgb_triple[0], g=rgb_triple[1], b=rgb_triple[2], effect=rmled.EFFECT_BREATH)
        last_idleledtick = cv2.getTickCount()
  
      # check if the object kicks in
      if selected_trackidx is not None:
        new_status = "follow"
      else:
        new_status = "idle"

    elif status == "wakeup":
      # wakeup state
      if prev_status != "wakeup":
        ep_chassis.drive_wheels(w1=0, w2=0, w3=0, w4=0, timeout=0)

      # led effect
      if last_ledtick > last_wakeupledtick or prev_status != "wakeup":
        ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=rgb_triple[0], g=rgb_triple[1], b=rgb_triple[2], effect=rmled.EFFECT_FLASH, freq=1)
        last_wakeupledtick = cv2.getTickCount()

      if instatus_ticks > wakeup_timeout * cv2.getTickFrequency():
        new_status = "search"
      else:
        new_status = "wakeup"

    elif status == "hit":
      # we have been hit

      # perform recovery maneuver
      if instatus_ticks < 2 * cv2.getTickFrequency():
        if armor_id == 1:
          # back
          speed_x = +0.12
          speed_y = 0
          speed_z = 0
        elif armor_id == 2:
          # front
          speed_x = -0.12
          speed_y = 0
          speed_z = 10 # steer right
        elif armor_id == 3:
          # left
          speed_x = 0
          speed_y = +0.12
          speed_z = 0
        elif armor_id == 4:
          # right
          speed_x = 0
          speed_y = -0.12
          speed_z = 0
        ep_chassis.drive_speed(x=speed_x, y=speed_y, z=speed_z, timeout=0)
        new_status = "hit"
      else:
        new_status = "idle"

    elif status == "explore":
      # exploration mode
      
      # first time here
      if prev_status != "explore":
        pass
      new_status = "explore"

      # led effect
      if last_ledtick > last_exploreledtick or prev_status != "explore":
        ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, r=rgb_triple[0], g=rgb_triple[1], b=rgb_triple[2], effect=rmled.EFFECT_SCROLLING, freq=1)
        last_exploreledtick = cv2.getTickCount()

    else:
      # should not be here
      new_status = "wakeup"

    # override status change here

    # got an hit
    if has_robot and cv2.getTickCount() - last_hittick < 0.5 * cv2.getTickFrequency():
      new_status = "hit"

    # bumping into something
    if False and has_robot:
      wanted_speed = math.sqrt(speed_x*speed_x+speed_y*speed_y+speed_z*speed_z)
      real_speed = math.sqrt(robot_vel[3]*robot_vel[3]+robot_vel[4]*robot_vel[4]+robot_vel[5]*robot_vel[5])
      #print(wanted_speed, real_speed)
      #if 10*real_speed < wanted_speed:
      #  print("BUMP!")
      if wanted_speed > 0.9 and real_speed < 0.05:
        print("BUMP!")
        armor_id = 2
        new_status = "hit"

    # tracker is not responding
    if inst_rtt < 0 and status != "search" and cv2.getTickCount() - last_dettick > 1 * cv2.getTickFrequency():
      new_status = "idle"

    # force a new status
    if forced_status:
      new_status = forced_status
      forced_status = None

    # update status and instatus time
    prev_status = status
    status = new_status
    if new_status != prev_status:
      last_changeticks = cv2.getTickCount()
    instatus_ticks = cv2.getTickCount() - last_changeticks

    # quick check
    time.sleep(0.025)

  # close the robot
  if a.dji and has_robot:
    ep_led.set_gimbal_led(comp=rmled.COMP_TOP_ALL, g=0, r=0, b=0, effect=rmled.EFFECT_OFF, led_list=[0, 1, 2, 3, 4, 5, 6, 7])
    ep_led.set_led(comp=rmled.COMP_BOTTOM_ALL, g=0, r=0, b=0, effect=rmled.EFFECT_OFF)
    ep_chassis.unsub_position()
    #ep_armor.unsub_hit_event()
    ep_robot.close()
    print("robot closed")

  print("status stopped")


####################
# detection thread #
####################

# simple random number generator
def lcg(x, a, c, m):
  return (a * x + c) % m

# the thread itself    
def det_thread(a):

  print("detection started")

  global img
  global jpegbuffer
  global last_jpegtick
  global last_captick
  global frmnum
  global inst_proc_fps
  global det_response
  global processing
  global inst_rtt
  global last_dettick
  global trackobjects
  global ep_led
  global speed_x
  global speed_z
  global height
  global last_hittick
  global armor_id
  global rgb_triple
  global pathimg
  global last_ledtick
  last_ledtick = 0
  pathimg = None
  height = 0
  last_hittick = 0  
  speed_x = 0
  speed_z = 0
  trackobjects = list()
  font = cv2.FONT_HERSHEY_PLAIN
  last_captick = 0
  last_jpegtick = 1
  last_dettick = 1
  last_conntick = 0
  selected_trackidx = None
  ipv4_previous = 0
  while processing:

    # do this only when necessary
    if last_captick > last_dettick:
      
      # copy image locally
      img2 = img

      # prepare the video frame
      cfrm = VideoFrame(number=frmnum, timestamp=cv2.getTickCount(), img=cv2.imencode(".jpg", img2, [int(cv2.IMWRITE_JPEG_QUALITY), 98])[1].tobytes())

      # prepare a gRPC request
      detrequest = ObjectDetectionRequest(user_id=1, max_results=a.objects, frame=cfrm, wantface=not a.speed, wantyolo=not a.speed)

      # get a detection
      prevlastproctick = last_dettick
      try:
        # exec the RPC
        det_response = objdet_client.ObjectDetect(detrequest, timeout=1)
        last_dettick = cv2.getTickCount()
        inst_rtt = 1000 * (last_dettick - det_response.timestamp) / cv2.getTickFrequency()
      except: 
        # open communication channel
        if cv2.getTickCount() - last_conntick > 1 * cv2.getTickFrequency():
          last_conntick = cv2.getTickCount()
          try:
            print("Connection attempt")
            objectdetection_host = os.getenv("OBJECTDETECTION_HOST", a.address)
            objectdetection_channel = grpc.insecure_channel(objectdetection_host)
            objdet_client = ObjectDetectionStub(objectdetection_channel)
          except:
            pass
        # prepare faux response
        det_response = None
        inst_rtt = -1

      # calculate fps
      try:
        inst_proc_fps = cv2.getTickFrequency() / (last_dettick - prevlastproctick)
      except:
        inst_proc_fps = 0

      # change led colors
      if has_robot:
        if det_response:
          ipv4 = int(det_response.ipv4) 
          if ipv4 != ipv4_previous:
            if ipv4 == 183763437:
              rgb_triple = (255, 0, 0)
            elif ipv4 == 183763130:
              rgb_triple = (0, 255, 0)
            else:
              bsdrand = lcg(ipv4, 734534569345, 12345, 0xffffffff)
              rgb_triple = (bsdrand&0x000000ff, (bsdrand>>8)&0x000000ff, (bsdrand>>16)&0x000000ff)
            ipv4_previous = ipv4
            last_ledtick = cv2.getTickCount()
        else:
          ipv4 = 0
          if ipv4 != ipv4_previous:
            rgb_triple = (64, 64, 64)
            ipv4_previous = ipv4
            last_ledtick = cv2.getTickCount()
        #print(rgb_triple)
          
      # render the response graphically
      if a.webserve and height > 0:
          # top information
          cv2.putText(img2, f"{frmnum:5d}:{inst_rtt:.0f}", (0, 15), font, 1, (0, 255, 0), 1)

          # bottom information
          cv2.putText(img2, f"SX:{speed_x:.3f}", (10, int(height) - 25), font, 1, (0, 0, 255), 1)
          cv2.putText(img2, f"SZ:{speed_z:.3f}", (10, int(height) - 10), font, 1, (0, 0, 255), 1)

          # hits
          if has_robot and cv2.getTickCount() - last_hittick < 0.7 * cv2.getTickFrequency():
            if armor_id == 1:
              cv2.line(img2, (0, int(height) - 1), (int(width) - 1, int(height) - 1), (255, 0, 255), 3)
            elif armor_id == 2:
              cv2.line(img2, (0, 0), (int(width) - 1, 0), (255, 0, 255), 3)
            elif armor_id == 3:
              cv2.line(img2, (0, 0), (0, int(height) - 1), (255, 0, 255), 3)
            elif armor_id == 4:
              cv2.line(img2, (int(width) - 1, 0), (int(width) - 1, int(height) - 1), (255, 0, 255), 3)

          # loop over the tracked objects
          if a.trackobj:
            for tidx, trackobject in enumerate(trackobjects):
              # the color is initially vivid, then it washes out
              color = (0, 0, 255 - trackobject.missing*5) if tidx == selected_trackidx else (255 - trackobject.missing*5, 0, 0)
              #color = trackobject.color
              thickness = 2 if tidx == selected_trackidx else 1
              # a rectangle encloses the object
              cv2.rectangle(img2, (int(trackobject.cx - trackobject.width/2), int(trackobject.cy - trackobject.height/2)), (int(trackobject.cx + trackobject.width/2), int(trackobject.cy + trackobject.height/2)), color, thickness)
              # a cross indicates the centroid
              cv2.line(img2, (int(trackobject.cx - 3), int(trackobject.cy - 3)), (int(trackobject.cx + 3), int(trackobject.cy + 3)), [255 - color[0], 255 - color[1], 255 - color[2]], thickness)
              cv2.line(img2, (int(trackobject.cx - 3), int(trackobject.cy + 3)), (int(trackobject.cx + 3), int(trackobject.cy - 3)), [255 - color[0], 255 - color[1], 255 - color[2]], thickness)
              # a descriptor
              cv2.putText(img2, f"{trackobject.oid}: {trackobject.name}", (int(trackobject.cx - trackobject.width/2), int(trackobject.cy - trackobject.height/2 - 3)), font, 0.6, color, 1)

          elif det_response:

            # loop over the detected objects
            for didx, detobject in enumerate(det_response.objects):
              color = (0, 255, 0) 
              # a rectangle encloses the object
              cv2.rectangle(img2, (detobject.x, detobject.y), (detobject.x + detobject.w, detobject.y + detobject.h), color, 1)
              # a tiny descriptor
              cv2.putText(img2, f"{didx}: {detobject.name}", (detobject.x, detobject.y - 3), font, 0.6, color, 1)

          # overlay path image
          if pathimg is not None:
            img2 = cv2.addWeighted(img2, 1, pathimg, 1, 0.0)
          else:
            pathimg = np.zeros((height,width,4), np.uint8)
            #pathimg = np.random.randint(0, 255, size=(height, width, 4), dtype=np.uint8)

          # compress the image
          jpegbuffer = cv2.imencode(".jpg", img2, [int(cv2.IMWRITE_JPEG_QUALITY), 98])[1].tobytes()
          last_jpegtick = cv2.getTickCount()
    
    time.sleep(0.01)

  print("detection stopped")


#######################
# webcam/video thread #
#######################
def webcam_video_thread(a):

  global width
  global height
  width = 0
  height = 0
  raspicam = False
  if a.input.isnumeric():
    print("Opening camera: " + a.input)
    cap = cv2.VideoCapture(int(a.input), cv2.CAP_V4L2)
    if cap.isOpened() is False:
      print("Error opening video stream")
      return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    #cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')) # enable this to lower the CPU load
    cap.set(cv2.CAP_PROP_FPS, 30)
    #cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    print(width, "x", height, "@", cap.get(cv2.CAP_PROP_FPS), "EXP", cap.get(cv2.CAP_PROP_AUTO_EXPOSURE))
  elif a.input == "raspicam":
     print("Opening raspberry camera")   
     picam2 = Picamera2()
     video_config = picam2.create_video_configuration({"format": 'XRGB8888', "size": (640, 480)})
     #print(video_config)
     picam2.configure(video_config)
     picam2.start()
     raspicam = True
  else:
    print("Opening file: " + a.input)
    cap = cv2.VideoCapture(a.input)
    if not cap.isOpened():
      print("Error opening file")
      return

  # get the pictures
  global img
  global last_captick
  global frmnum
  global inst_acq_fps
  global processing
  frmnum = 0
  while processing:

    # this call is blocking for a webcam
    prevlastcaptick = last_captick
    if raspicam:
      try:
        img = picam2.capture_array()
        ret = True
      except:
        ret = False
    else:
      ret, img = cap.read()
    last_captick = cv2.getTickCount()

    # recalc center
    if img.shape[1] != width:
      height = img.shape[0]
      width = img.shape[1]

    # calculate the fps
    try:
      inst_acq_fps = cv2.getTickFrequency() / (last_captick - prevlastcaptick)
    except:
      inst_acq_fps = 0

    #frmnum = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    frmnum = frmnum + 1
    if not ret:
      if args.repeat and not raspicam:
        # Restarts the video since it is probably ended
        cap = cv2.VideoCapture(args.input)
        ret, img = cap.read()
        if not ret:
          # Uhm, some other problem
          print("Problem reading from input")
          break
      else:
        # Uhm, some other problem
        print("Problem reading from input")
        break

  # when everything is done, release the capture
  if raspicam:
    picam2.stop()
  else:
    cap.release()
  print("video stopped")


####################################
# Motion JPEG server for debugging #
####################################
global jpegbuffer
dir_path = os.path.dirname(os.path.realpath(__file__))
with open(dir_path + "/liquid_edge_paused.jpg", mode='rb') as file: # b is important -> binary
  jpegbuffer = file.read()
global pausedjpegbuffer
pausedjpegbuffer = jpegbuffer
global last_jpegtick
last_jpegtick = cv2.getTickCount()

class MJPEGServerThread(threading.Thread):

  def __init__(self, app):
    threading.Thread.__init__(self)
    self.server = werkzeug.serving.make_server('0.0.0.0', 9088, app)
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
  global last_jpegtick
  global jpegbuffer
  global pausedjpegbuffer
  while keepRunning:
    agetime = (cv2.getTickCount() - last_jpegtick) / cv2.getTickFrequency()
    if agetime > 2:
      jpegbuffer = pausedjpegbuffer
      last_jpegtick = cv2.getTickCount()
    else:
      yield memoryview(jpegbuffer)
    time.sleep(0.010)

def startMJPEGserver():
  global keepRunning
  keepRunning = True
  global MJPEGserver
  app = flask.Flask('myapp')

  @app.route('/')
  def stream():
    return mjpeg.server.MJPEGResponse(relay())  
  
  MJPEGserver = MJPEGServerThread(app)
  MJPEGserver.start()

def stopMJPEGserver():
  global MJPEGserver
  global keepRunning
  keepRunning = False
  MJPEGserver.shutdown()


########
# main #
########
if __name__ == "__main__":

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
  parser.add_argument("-i", "--input", help="Enter camera number, 'raspicam', or a file path", default="../liquid-edge-model-zoo/clips/manhattanwalk_854x480.mp4", dest="input")
  #parser.add_argument("-i", "--input", help="Enter camera number or a file path", default="../liquid-edge-model-zoo/clips/trainer_480p.mp4", dest="input")
  parser.add_argument("-a", "--alpha", help="FPS averaging constant", default="0.97", dest="alpha", type=float)
  parser.add_argument("-o", "--max-objects", help="Number of max. reported objects", default="10", dest="objects", type=int)
  parser.add_argument("-t", "--object-type", help="Type of object to track", default="face", dest="objecttype", type=str)
  parser.add_argument("-l", "--log-file", help="Log results to file", action="store_true", dest="logfile", default=None)
  parser.add_argument("-w", "--web-serve", help="Web server for camera viewing on port 9088", default=False, action='store_true', dest='webserve')
  parser.add_argument("-p", "--pathmap", help="Create path map", default=False, action='store_true', dest='pathmap')
  parser.add_argument("-V", "--version", action="version", version="0.2")
  parser.add_argument("address", help="Server address:port (or environment variable)", default="localhost:50051", nargs="?")
  args = parser.parse_args()

  # associate CTRL-C to handler
  #signal.signal(signal.SIGINT, sighandler)

  # initialize log file
  global lf
  lf = None
  if args.logfile:
    try:
      lf = open("logfile.csv", 'w')
      lf.write('"time","rtt","objnum","x","y","z"\n')
    except:
      pass

  # start web server for debugging
  if args.webserve:
    startMJPEGserver()

  # start watching keyboard
  kb = kbhit.KBHit()

  # start video capture
  videothr = threading.Thread(target=webcam_video_thread, args=(args,))
  videothr.start()

  # start video detection
  detthr = threading.Thread(target=det_thread, args=(args,))
  detthr.start()

  # start tracking
  trackthr = threading.Thread(target=track_thread, args=(args,))
  trackthr.start()

  # start navigation
  navithr = threading.Thread(target=navi_thread, args=(args,))
  navithr.start()

  # start status
  statusthr = threading.Thread(target=status_thread, args=(args,))
  statusthr.start()

  # loop variables
  global inst_proc_fps
  global inst_acq_fps
  global det_response
  global inst_rtt
  global trackobjects
  global selected_trackidx
  global status
  global e_lr
  global e_fb
  global has_robot
  global forced_status
  global robot_pos
  global robot_vel
  robot_vel = [0,0,0,0,0,0]
  robot_pos = [0,0,0]
  forced_status = None
  has_robot = False
  e_lr = 0
  e_fb = 0
  status = ''
  selected_trackidx = None
  trackobjects = list()
  inst_proc_fps = 0
  inst_acq_fps = 0
  det_response = None
  last_printtick = -1
  last_logtick = -1
  inst_rtt = 0
  while processing:

    # get key presses
    if kb.kbhit():
      c = kb.getch()
      if c == 'q' or c == 'k':
        # terminate program
        processing = False
      elif c == 's':
        # force searching
        forced_status = "search"
      elif c == 'i':
        # force idle
        forced_status = "idle"
      elif c == 'x':
        # force exploration
        forced_status = "explore"

    # current network interface
    with open("/tmp/currentovsport","r") as f:
      ovsport = f.read().rstrip()

    # print something
    if cv2.getTickCount() - last_printtick > 1*cv2.getTickFrequency():
      print("%s a:%.1f p:%.1f d:%d t:%d f:%d rtt:%.0f s:%s  %.2f %.2f %.2f,%.2f,%.2f,(%.2f) " % (ovsport, inst_acq_fps, inst_proc_fps, len(det_response.objects) if det_response else 0, 
      len(trackobjects), 1 if selected_trackidx is not None else 0, inst_rtt, status, e_lr, e_fb, 
      robot_pos[0], robot_pos[1], robot_pos[2], robot_vel[3]), end="\r", flush=True)
      last_printtick = cv2.getTickCount()

    # log something
    if lf and cv2.getTickCount() - last_logtick > 0.25*cv2.getTickFrequency():
      lf.write("%f,%.1f,%d,%.2f,%.2f,%.2f,%.1f,%s\n" % (time.time(), inst_rtt, len(det_response.objects) if det_response else 0, robot_pos[0], robot_pos[1], robot_pos[2], inst_proc_fps, ovsport))
      last_logtick = cv2.getTickCount()

    # be responsive
    time.sleep(0.01)

  # stop watching keyboard
  kb.set_normal_term()

  # stop serving the web
  if args.webserve:
    stopMJPEGserver()

  # stop the video
  videothr.join()

  # stop video detection
  detthr.join()

  # stop tracking
  trackthr.join()

  # stop navigation
  navithr.join()

  # stop status
  statusthr.join()

  # print digest
  if lf:
    lf.close()
