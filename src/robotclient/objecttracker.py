# import the necessary packages
import math
import numpy as np

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
    self.regobjects: list(Object) = []

		# number of maximum consecutive frames a given object is allowed to be marked as "missing" until we need to deregister it from tracking
    self.maxMissing = maxMissing


  def register(self, object: Object):
    # when registering an object we use the next available object ID to store it
    object.oid = self.nextRegObjectID
    self.regobjects.append(object)
    self.nextRegObjectID += 1


  def update(self, detobjects):
    # # arrays of centroid colors
    # detcolors = [[0, 0, 0]]*len(detobjects)
    # for didx, detobject in enumerate(detobjects):
    #   average_color_row = np.average(img[int(detobject.y + detobject.h/2) - 2:int(detobject.y + detobject.h/2) + 2, int(detobject.x + detobject.w/2) - 2:int(detobject.x + detobject.w/2) + 2], axis=0)
    #   detcolors[didx] = np.average(average_color_row, axis=0)
    #   #detcolors[didx] = img[int(detobject.y + detobject.h/2), int(detobject.x + detobject.w/2)]       
      
    # in case there are no registered objects, create them and go out
    if len(self.regobjects) == 0:
      for didx, detobject in enumerate(detobjects):
        self.register(Object(detobject.x + detobject.w/2, detobject.y + detobject.h/2, detobject.w, detobject.h, detobject.name, [detobject.b, detobject.g, detobject.r]))
      return self.regobjects
      
    # array of mutual distances: rows are registered o., columns are detected o., name of o. is verified
    MyMetrics = [[math.inf for i in range(len(detobjects))] for j in range(len(self.regobjects))]
    regchosens = [False]*len(self.regobjects)
    detchosens = [False]*len(detobjects)
    alpha = 0.999 # memory of new detection
    for ridx, regobject in enumerate(self.regobjects):
      for didx, detobject in enumerate(detobjects):
        if regobject.name == detobject.name:
          colorMetric = (float(regobject.color[0]) - float(detobject.b))**2 + (float(regobject.color[1]) - float(detobject.g))**2 + (float(regobject.color[2]) - float(detobject.r))**2
          distMetric = (regobject.cx - (detobject.x + detobject.w/2))**2 + (regobject.cy - (detobject.y + detobject.h/2))**2
          MyMetrics[ridx][didx] = (1-alpha)*colorMetric/195075 + alpha*distMetric/1566976
          # MyMetrics[ridx][didx] = math.sqrt((regobject.cx - (detobject.x + detobject.w/2))**2 + (regobject.cy - (detobject.y + detobject.h/2))**2)
          # MyMetrics[ridx][didx] = ((regobject.cx - regobject.width/2) - detobject.x)**2 + ((regobject.cy - regobject.height/2) - detobject.y)**2 
          # + ((regobject.cx + regobject.width/2) - detobject.x - detobject.w)**2 + ((regobject.cy + regobject.height/2) - detobject.y)**2 
          # + ((regobject.cx - regobject.width/2) - detobject.x)**2 + ((regobject.cy + regobject.height/2) - detobject.y - detobject.h)**2 
          # + ((regobject.cx + regobject.width/2) - detobject.x - detobject.w)**2 + ((regobject.cy + regobject.height/2) - detobject.y - detobject.h)**2

    # find the registered o. nearest to a detected o.
    for didx, detobject in enumerate(detobjects):
      if not detchosens[didx]:
        ridxmin = None
        distmin = math.inf
        for ridx, regobject in enumerate(self.regobjects):
          if not regchosens[ridx] and MyMetrics[ridx][didx] < distmin:
            distmin = MyMetrics[ridx][didx]
            ridxmin = ridx
        if distmin < math.inf:    
          # verify it is the smallest horizontally
          smallest = True
          for didx2 in range(len(detobjects)):
            if not detchosens[didx2] and MyMetrics[ridxmin][didx2] < distmin:
              smallest = False
              break
          # update registered
          if smallest:
            beta = 0.5 # IIR filtering constant
            self.regobjects[ridxmin].cx = beta*self.regobjects[ridxmin].cx + (1 - beta)*(detobjects[didx].x + detobjects[didx].w/2)
            self.regobjects[ridxmin].cy = beta*self.regobjects[ridxmin].cy + (1 - beta)*(detobjects[didx].y + detobjects[didx].h/2)
            self.regobjects[ridxmin].width = beta*self.regobjects[ridxmin].width + (1 - beta)*detobjects[didx].w
            self.regobjects[ridxmin].height = beta*self.regobjects[ridxmin].height + (1 - beta)*detobjects[didx].h
            self.regobjects[ridxmin].missing = 0
            self.regobjects[ridxmin].color[0] = beta*self.regobjects[ridxmin].color[0] + (1 - beta)*detobject.b
            self.regobjects[ridxmin].color[1] = beta*self.regobjects[ridxmin].color[1] + (1 - beta)*detobject.g
            self.regobjects[ridxmin].color[2] = beta*self.regobjects[ridxmin].color[2] + (1 - beta)*detobject.r
            # mark the pairing as done
            regchosens[ridxmin] = True
            detchosens[didx] = True

    # control missing registered o.
    for ridx, regobject in enumerate(self.regobjects):
      if not regchosens[ridx]:
        regobject.missing += 1

    # purge old missing registered o.
    self.regobjects[:] = [regobject for regobject in self.regobjects if regobject.missing < self.maxMissing]

    # insert new detected o.
    for didx, detobject in enumerate(detobjects):
      if not detchosens[didx]:
        self.register(Object(detobject.x + detobject.w/2, detobject.y + detobject.h/2, detobject.w, detobject.h, detobject.name, [detobject.b, detobject.g, detobject.r]))

    return self.regobjects
