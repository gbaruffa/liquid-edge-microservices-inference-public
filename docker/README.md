# LIQUID EDGE Docker builds

![LIQUID EDGE Logo](../doc/liquid_edge_logo28.png)

> These programs are a part of the system used for the LIQUID EDGE PRIN 2017 project demonstrator.

Build the container with Python 3.6 + OpenCV 4.5 + CUDA 11 + cuDNN 8.8.

```cli
$ docker build -t "python3.8-cuda11.7.1-opencv4.6" .
```

Enter inside the container writing in Terminal:

```cli
$ docker run -it --entrypoint /bin/bash python3.8-cuda11.7.1-opencv4.6
```

Set the path of cv2 inside the container writing inside the Dockefile:

```cli
$ RUN echo "import site" >> /etc/python3.8/sitecustomize.py
$ RUN echo 'site.addsitedir("/usr/local/lib/python3.8/site-packages/")' >> /etc/python3.8/sitecustomize.py
```

Note: place the libcudnn* DEB files in this folder before the build.