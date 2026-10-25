"""Build the two fictional class schedules the schedule tests use.

Both are watermarked "SAMPLE · TEST DATA" and name a fictional student (TEST-0101).
Course codes and the printed formats mirror a De Anza "My Class Schedule" page so the
parser sees what a real one looks like; the student, CRNs, rooms and instructors are invented.

    uv run --with reportlab --with pillow python tests/fixtures/schedule/make_fixtures.py

- sample-schedule.pdf: a "My Class Schedule" page, Fall 2026, one block per class, with
  class dates, a lecture + lab pair, an online synchronous class and an asynchronous one.
- sample-schedule.png: a screenshot of a schedule table, Winter 2027, with a TBA row and
  times printed without AM/PM on the start.

recorded/*.json are the rows Claude returned for each file (one live call each); the tests
replay them instead of calling Claude.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import Color, HexColor, black
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
W, H = letter
DISCLAIMER = "SAMPLE FOR SOFTWARE TESTING ONLY. NOT A REAL STUDENT'S SCHEDULE."
STUDENT = "Student: Test Student One        ID: TEST-0101"

# (crn, course, title, section, instructor, units, meetings[(days, time, location, method)], dates)
FALL = [
    ("40112", "MATH D001B", "Calculus II", "01", "Test Instructor A", "5.0",
     [("MW", "9:30 AM - 11:20 AM", "S44", "In Person")], "09/21/2026 - 12/11/2026"),
    ("40387", "CIS D022C", "Data Abstraction and Structures", "61Y", "Test Instructor B", "4.5",
     [("TTh", "1:30 PM - 3:20 PM", "AT 203", "Hybrid"), ("F", "10:30 AM - 12:20 PM", "AT 312", "Hybrid")],
     "09/21/2026 - 12/11/2026"),
    ("40521", "ENGL C1000", "Academic Reading and Writing", "02Z", "Test Instructor C", "5.0",
     [("TTh", "9:30 AM - 11:20 AM", "ONLINE", "Online Synchronous")], "09/21/2026 - 12/11/2026"),
    ("40966", "ECON D001A", "Principles of Macroeconomics", "63Z", "Test Instructor D", "4.0",
     [("", "", "ONLINE", "Online Asynchronous")], "09/21/2026 - 12/11/2026"),
]

WINTER = [
    ("CRN", "Course", "Title", "Sec", "Instructor", "Units", "Days", "Time", "Location", "Method"),
    ("10234", "MATH D001C", "Calculus III", "03", "Test Instructor E", "5.0", "TTh", "11:30-1:20 PM", "S46", "In Person"),
    ("10478", "CIS D035A", "Java Programming", "01", "Test Instructor F", "4.5", "MW", "6:00 PM-8:15 PM", "AT 204", "In Person"),
    ("10519", "STAT C1000", "Introduction to Statistics", "22Z", "Test Instructor G", "5.0", "TBA", "TBA", "ONLINE", "Online Asynchronous"),
    ("10602", "PHYS D004A", "Physics for Scientists and Engineers", "01", "Test Instructor H", "6.0", "MWF", "8:30 AM-9:20 AM", "S16", "Hybrid"),
]


def watermark(c: canvas.Canvas) -> None:
    c.saveState()
    c.setFillColor(Color(0.9, 0.2, 0.2, alpha=0.13))
    c.setFont("Helvetica-Bold", 78)
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "SAMPLE · TEST DATA")
    c.restoreState()


def pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("SAMPLE · TEST DATA · My Class Schedule · Fall 2026 · TEST-0101")
    watermark(c)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, H - 60, "De Anza College — My Class Schedule")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(HexColor("#b03a2e"))
    c.drawString(54, H - 76, DISCLAIMER)
    c.setFillColor(black)
    c.setFont("Helvetica", 10)
    c.drawString(54, H - 96, STUDENT)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(54, H - 122, "Fall 2026 Quarter")
    y = H - 146
    for crn, course, title, sec, instructor, units, meetings, dates in FALL:
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(54, y, f"{course} - {title}")
        c.setFont("Helvetica", 9)
        c.drawString(54, y - 14, f"CRN: {crn}    Section: {sec}    Units: {units}    Instructor: {instructor}"
                                 f"    Status: Registered")
        y -= 32
        c.setFont("Helvetica-Bold", 8.5)
        for x, head in zip((64, 130, 260, 340, 460), ("Days", "Time", "Location", "Method", "Dates")):
            c.drawString(x, y, head)
        c.setFont("Helvetica", 8.5)
        for days, time, location, method in meetings:
            y -= 13
            for x, value in zip((64, 130, 260, 340, 460), (days or "-", time or "-", location, method, dates)):
                c.drawString(x, y, value)
        y -= 26
    c.setFont("Helvetica", 9)
    c.drawString(54, y, "Total Registered Units: 18.5")
    c.save()


def png(path: Path) -> None:
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
        bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
        big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
        mark = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 120)
    except OSError:
        font = bold = big = mark = ImageFont.load_default()
    widths = (90, 140, 370, 60, 200, 70, 70, 190, 110, 210)
    width = sum(widths) + 60
    image = Image.new("RGB", (width, 430), "white")
    d = ImageDraw.Draw(image)
    d.text((30, 24), "My Class Schedule — Winter 2027", font=big, fill="black")
    d.text((30, 64), f"SAMPLE · TEST DATA · {DISCLAIMER}", font=font, fill=(176, 58, 46))
    d.text((30, 92), STUDENT, font=font, fill=(60, 60, 60))
    y = 140
    for i, row in enumerate(WINTER):
        if i == 0:
            d.rectangle((30, y - 6, width - 30, y + 30), fill=(230, 233, 240))
        elif i % 2 == 0:
            d.rectangle((30, y - 6, width - 30, y + 30), fill=(247, 247, 247))
        x = 40
        for w, value in zip(widths, row):
            d.text((x, y), value, font=bold if i == 0 else font, fill="black")
            x += w
        y += 44
    d.text((30, y + 10), "Total Units: 20.5", font=bold, fill="black")
    overlay = Image.new("L", image.size, 0)
    ImageDraw.Draw(overlay).text((width // 2 - 620, 220), "SAMPLE · TEST DATA", font=mark, fill=60)
    image.paste(Image.new("RGB", image.size, (220, 60, 60)), (0, 0), overlay)
    image.save(path, optimize=True)


if __name__ == "__main__":
    pdf(HERE / "sample-schedule.pdf")
    png(HERE / "sample-schedule.png")
    print("wrote", HERE / "sample-schedule.pdf", HERE / "sample-schedule.png")
