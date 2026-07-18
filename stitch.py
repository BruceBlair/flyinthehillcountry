import cv2
import glob

imgs = []
for f in sorted(glob.glob("High*.jpg")):
    imgs.append(cv2.imread(f))

stitcher = cv2.Stitcher_create(cv2.Stitcher_SCANS)
status, pano = stitcher.stitch(imgs)

if status == cv2.Stitcher_OK:
    cv2.imwrite("pano.jpg", pano)
    print("Stitched pano saved as pano.jpg")
else:
    print("Stitching failed:", status)
