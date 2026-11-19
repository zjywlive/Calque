"""Build examples/sample-paper.pdf: a two-page, two-column paper-style PDF with original text,
a vector figure and a formula, used for the README screenshots and as a quick self-test.

    /usr/bin/python3 -E examples/make_sample.py
"""
import os

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 595, 842          # A4 in points
M, GAP = 48, 22          # margin, column gap
COL = (W - 2 * M - GAP) / 2
CSS = ("* {font-family: Times, serif;} p {margin: 0 0 6px 0; font-size: 9.6px; line-height: 1.32; text-align: justify;}"
       "h1 {font-size: 19px; text-align: center; margin: 0;} h2 {font-size: 10.5px; margin: 8px 0 4px 0;}"
       ".au {font-size: 10px; text-align: center; margin: 4px 0 0 0;} .ab {font-size: 9.2px; font-style: italic;}"
       ".cap {font-size: 8.6px; text-align: center;}")

TITLE = "Seeing Touch: A Short Primer on Optical Tactile Sensors"
AUTHORS = "A. Example and B. Sample — Example Robotics Lab"
ABSTRACT = ("<b>Abstract</b>—Optical tactile sensors turn contact into images. A soft skin deforms against an object, "
            "an internal camera records the deformation, and image processing recovers contact location, force and "
            "local shape. This primer explains the main design choices, compares marker-based and photometric "
            "approaches, and lists open problems for robots that must handle fragile objects.")
COL1 = [
    ("h2", "I. Introduction"),
    ("p", "Robots that grasp everyday objects need more than vision. When a gripper closes, the object is often "
          "hidden by the fingers, and small slips happen faster than a camera above the table can notice. Touch fills "
          "this gap: it reports where contact happens, how hard the fingers press and whether the object is starting "
          "to slide."),
    ("p", "Optical tactile sensors are attractive because they reuse cheap camera hardware. Instead of wiring "
          "hundreds of pressure cells, a single camera watches the inside of a soft fingertip. Every pixel becomes a "
          "measurement, so the spatial resolution is far higher than in most electronic skins."),
    ("h2", "II. How the Sensor Works"),
    ("p", "A typical design has three layers: an elastomer skin that touches the world, a transparent support that "
          "keeps the skin in shape, and a camera with controlled lighting. When the skin is pressed, the image "
          "changes in two ways. Markers printed on the skin move sideways, and the shading of the surface changes "
          "with its slope."),
    ("p", "Marker-based sensors track the dots and estimate shear and slip from their motion. Photometric sensors "
          "light the skin from several colours and recover the surface normal at every pixel, which gives a detailed "
          "depth map of the contact."),
]
COL2 = [
    ("p", "The relation between the measured normal and the depth of the skin can be written as a simple "
          "integration problem. If <i>n</i> is the normal at a pixel, the surface gradient is"),
    ("eq", "∇z = (−nₓ / n_z , −n_y / n_z)"),
    ("p", "and the depth map follows from integrating this gradient over the contact patch. In practice a small "
          "neural network often replaces the analytic model, because it also corrects lens distortion and uneven "
          "lighting."),
    ("fig", None),
    ("cap", "Fig. 1. Layers of an optical tactile fingertip: skin, support and camera."),
    ("h2", "III. Open Problems"),
    ("p", "Three problems remain. First, the soft skin wears out and must be replaced, which changes the calibration. "
          "Second, the camera needs space, so fingertips are bulky compared with human fingers. Third, sim-to-real "
          "transfer is difficult: simulated images rarely match the noise and lighting of a real sensor."),
]
PAGE2 = [
    ("h2", "IV. Choosing a Design"),
    ("p", "The right design depends on the task. For slip detection, markers are usually enough and are easy to "
          "track at high frame rates. For recognising small textures or reading the shape of a key, photometric "
          "sensing gives much richer information, at the cost of careful lighting design and calibration."),
    ("p", "Size matters as much as resolution. A sensor that does not fit on the finger of a dexterous hand cannot "
          "be used for in-hand manipulation, no matter how accurate it is in the lab."),
    ("h2", "V. Conclusion"),
    ("p", "Optical tactile sensors give robots a detailed sense of touch with simple hardware. The next steps are "
          "thinner fingertips, skins that last longer and simulation tools that make learning on real robots "
          "cheaper. With these, touch can become as routine in robotics as cameras are today."),
    ("h2", "References"),
    ("p", "[1] A. Example, “Soft skins for robot fingers,” Example Journal of Robotics, vol. 1, pp. 1–10, 2024."),
    ("p", "[2] B. Sample, “Photometric stereo in a fingertip,” Proc. Example Conf., pp. 11–20, 2025."),
]


def html(items):
    out = []
    for kind, text in items:
        if kind == "h2":
            out.append(f"<h2>{text}</h2>")
        elif kind == "p":
            out.append(f"<p>{text}</p>")
        elif kind == "eq":
            out.append(f"<p style='text-align:center;font-style:italic;font-size:10.5px'>{text}</p>")
        elif kind == "cap":
            out.append(f"<p class='cap'>{text}</p>")
    return "".join(out)


def figure(page, x, y, w):
    """Vector drawing of the three sensor layers."""
    h = 92
    page.draw_rect(fitz.Rect(x + 20, y + 8, x + w - 20, y + 22), color=(0.2, 0.2, 0.2), fill=(0.98, 0.78, 0.55), width=0.6)
    page.draw_rect(fitz.Rect(x + 20, y + 22, x + w - 20, y + 44), color=(0.2, 0.2, 0.2), fill=(0.85, 0.92, 0.98), width=0.6)
    page.draw_rect(fitz.Rect(x + w / 2 - 22, y + 58, x + w / 2 + 22, y + 82), color=(0.2, 0.2, 0.2), fill=(0.3, 0.3, 0.35), width=0.6)
    page.draw_circle(fitz.Point(x + w / 2, y + 58), 8, color=(0.2, 0.2, 0.2), fill=(0.55, 0.6, 0.7), width=0.6)
    for dx in (-60, -30, 0, 30, 60):
        page.draw_line(fitz.Point(x + w / 2, y + 52), fitz.Point(x + w / 2 + dx, y + 44), color=(0.5, 0.5, 0.5), width=0.4, dashes="[2 2] 0")
    return h


def main():
    doc = fitz.open()
    p = doc.new_page(width=W, height=H)
    p.insert_htmlbox(fitz.Rect(M, 56, W - M, 120), f"<h1>{TITLE}</h1><p class='au'>{AUTHORS}</p>", css=CSS)
    p.insert_htmlbox(fitz.Rect(M, 124, W - M, 190), f"<p class='ab'>{ABSTRACT}</p>", css=CSS)
    p.insert_htmlbox(fitz.Rect(M, 200, M + COL, H - M), html(COL1), css=CSS)
    x2 = M + COL + GAP
    before = [i for i in COL2[:COL2.index(("fig", None))]]
    after = COL2[COL2.index(("fig", None)) + 1:]
    p.insert_htmlbox(fitz.Rect(x2, 200, W - M, 330), html(before), css=CSS)
    fy = 324
    figure(p, x2, fy, COL)
    p.insert_htmlbox(fitz.Rect(x2, fy + 96, W - M, H - M), html(after), css=CSS)
    p.insert_text(fitz.Point(W / 2 - 3, H - 24), "1", fontsize=8, fontname="Times-Roman")
    p2 = doc.new_page(width=W, height=H)
    p2.insert_htmlbox(fitz.Rect(M, 56, M + COL, H - M), html(PAGE2), css=CSS)
    p2.insert_text(fitz.Point(W / 2 - 3, H - 24), "2", fontsize=8, fontname="Times-Roman")
    out = os.path.join(HERE, "sample-paper.pdf")
    doc.save(out, garbage=4, deflate=True)
    print(out)


if __name__ == "__main__":
    main()
