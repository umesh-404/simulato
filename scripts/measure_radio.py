"""Measure radio button properties from exam screenshots."""
import sys, cv2, numpy as np
from pathlib import Path

ROOT = Path("d:/Python Projects/simulato")
sys.path.insert(0, str(ROOT))

images = sorted((ROOT / "datasets/calibration/no-scroll").glob("*.jpg"))[:3]

for img_path in images:
    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print(f"\nImage: {img_path.name} ({w}x{h})")

    # Find divider
    search_x1, search_x2 = int(w * 0.35), int(w * 0.55)
    ct, cb = int(h * 0.15), int(h * 0.90)
    content = gray[ct:cb, search_x1:search_x2]
    sobel = cv2.Sobel(content, cv2.CV_64F, 1, 0, ksize=3)
    col_sums = np.sum(np.abs(sobel), axis=0)
    divider_x = search_x1 + int(np.argmax(col_sums))
    print(f"Divider x: {divider_x} ({divider_x / w * 100:.1f}%)")

    # Search narrow strip after divider for radio buttons
    sx1, sx2 = divider_x + 5, min(w, divider_x + 120)
    strip = gray[ct:cb, sx1:sx2]
    sh, sw = strip.shape[:2]

    _, binary = cv2.threshold(strip, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    circles = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 50 or area > 3000:
            continue
        per = cv2.arcLength(cnt, True)
        if per == 0:
            continue
        circ = 4 * 3.14159 * area / (per * per)
        (cx, cy), r = cv2.minEnclosingCircle(cnt)
        if circ > 0.4 and 3 <= r <= 30:
            circles.append((sx1 + int(cx), ct + int(cy), r, area, circ))

    circles.sort(key=lambda c: c[1])
    print(f"Contour circles in strip [{sx1},{sx2}] (w={sw}px): {len(circles)}")
    for cx, cy, r, a, c in circles:
        print(f"  ({cx},{cy}) r={r:.1f} area={a:.0f} circ={c:.2f}")

    # Also HoughCircles on narrow strip with different params
    blurred = cv2.GaussianBlur(strip, (9, 9), 2)
    for p2 in [15, 20, 25, 30]:
        hc = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=1.2, minDist=30,
            param1=80, param2=p2,
            minRadius=5, maxRadius=25,
        )
        count = len(hc[0]) if hc is not None else 0
        if count > 0:
            hc_list = np.round(hc[0]).astype(int)
            print(f"Hough (p2={p2}): {count} circles")
            for cx, cy, cr in sorted(hc_list, key=lambda c: c[1]):
                print(f"  ({sx1 + cx},{ct + cy}) r={cr}")
            break  # Show first working param2
        else:
            print(f"Hough (p2={p2}): 0")

    # Measure the typical gray values in the radio button area
    # Sample a few vertical slices to understand the contrast
    print(f"\nGray value samples at strip center (col={sw // 2}):")
    for frac in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7]:
        y = int(sh * frac)
        vals = strip[y, :]
        print(f"  y={ct + y} ({frac:.0%}): min={vals.min()} max={vals.max()} mean={vals.mean():.0f}")
