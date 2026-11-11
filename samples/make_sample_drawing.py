"""Generate a synthetic utility design drawing for testing (not a real job).

Usage: python samples/make_sample_drawing.py samples/sample_drawing.pdf
"""

import sys

import pymupdf as fitz


def make(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)  # 17 x 11 in
    # Road (two edges and centerline) and right-of-way
    for y in (330, 450):
        page.draw_line((40, y), (980, y), color=(0, 0, 0), width=1.2)
    page.draw_line((40, 390), (980, 390), color=(0.4, 0.4, 0.4), width=0.8, dashes="[12 8] 0")
    page.insert_text((420, 395), "E UNIVERSITY DR", fontsize=12)
    page.draw_line((600, 120), (600, 330), color=(0, 0, 0), width=1.2)
    page.draw_line((680, 120), (680, 330), color=(0, 0, 0), width=1.2)
    page.insert_text((612, 200), "S RURAL RD", fontsize=10, rotate=90)

    # Poles and labels (scale 1" = 40', so 72 pt = 40 ft)
    items = [
        (300, 470, "REMOVE EXIST. 40' POLE"),
        (300, 500, "CONSTRUCT 45' CL2 POLE"),
        (420, 470, "REMOVE TRANSFORMER"),
        (420, 500, "CONSTRUCT 50 KVA XFMR"),
        (520, 470, "CONSTRUCT"),
    ]
    for x, y, text in items:
        page.draw_circle((x, 462), 5, color=(0, 0, 0), fill=(1, 1, 1))
        page.insert_text((x + 10, y), text, fontsize=8)
    page.insert_text((530, 482), "SPAN #2 PRIMARY", fontsize=8)

    # General notes (should NOT become work items)
    page.insert_text((60, 600), "GENERAL NOTES", fontsize=10)
    notes = [
        "1. ALL REMOVED MATERIAL SHALL BE RETURNED TO THE YARD.",
        "2. CONTRACTOR SHALL CALL AZ811 PRIOR TO EXCAVATION.",
        "3. CONSTRUCT PER UTILITY STANDARDS LATEST REVISION.",
    ]
    for i, n in enumerate(notes):
        page.insert_text((60, 616 + i * 13), n, fontsize=8)

    # Title block (right edge)
    page.draw_rect(fitz.Rect(1010, 20, 1204, 772), color=(0, 0, 0), width=1)
    tb = ["ELECTRIC UTILITY", "DISTRIBUTION DESIGN", "W.O. # 7654321", "1200 E UNIVERSITY DR", "TEMPE, AZ", "SCALE: 1\" = 40'", "SHEET 1 OF 1"]
    for i, t in enumerate(tb):
        page.insert_text((1020, 60 + i * 22), t, fontsize=9)
    page.insert_text((60, 760), "SCALE: 1\" = 40'", fontsize=9)
    doc.save(path)


if __name__ == "__main__":
    make(sys.argv[1] if len(sys.argv) > 1 else "samples/sample_drawing.pdf")
