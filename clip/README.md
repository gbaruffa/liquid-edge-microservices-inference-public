# LIQUID EDGE Microservices Inference

![LIQUID EDGE Logo](../doc/liquid_edge_logo28.png)

> These programs are a part of the system used for the LIQUID EDGE PRIN 2017 project demonstrator.

## Instruction for creating the "samplevideo" file
1. Download (in this folder) the following files from the Xiph website, https://media.xiph.org/video/derf/
* _Netflix_BarScene_4096x2160_60fps_10bit_420.webm_
* _Netflix_BoxingPractice_4096x2160_60fps_10bit_420.webm_
* _Netflix_Crosswalk_4096x2160_60fps_10bit_420.webm_
* _Netflix_DrivingPOV_4096x2160_60fps_10bit_420.webm_
* _Netflix_FoodMarket2_4096x2160_60fps_10bit_420.webm_
* _Netflix_Narrator_4096x2160_60fps_10bit_420.webm_
* _Netflix_RitualDance_4096x2160_60fps_10bit_420.webm_
* _Netflix_SquareAndTimelapse_4096x2160_60fps_10bit_420.webm_
* _Netflix_Tango_4096x2160_60fps_10bit_420.webm_

2. Install ```ffmpeg```

3. Open a terminal (in this folder) and run the command
```cli
$ ffmpeg -f concat -i .\concat.txt -vf scale=-1:480,fps=30 -c:v libx264 -preset slow -crf 22 -profile:v main -c:a none -f mp4 -y samplevideo_910_480.mp4
```