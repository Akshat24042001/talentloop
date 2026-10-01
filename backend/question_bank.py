"""Starter question bank: quantitative, logical, English, IT hardware, sales awareness and computer basics.

Each answer was worked out by hand (answer = index of the correct option). HR can edit or deactivate any question,
import their own from Excel, or draft more with AI. Loading the starter bank twice doesn't duplicate questions.
"""
from . import db

Q = [
    # --- quantitative
    ("quantitative", "easy", "A laptop is sold for Rs 40,000 after a 20% discount. What was the marked price?", ["Rs 45,000", "Rs 48,000", "Rs 50,000", "Rs 52,000"], 2, "40,000 / 0.8 = 50,000."),
    ("quantitative", "easy", "Monthly sales rose from Rs 2.5 lakh to Rs 3 lakh. What is the percentage increase?", ["15%", "20%", "25%", "30%"], 1, "0.5 / 2.5 = 20%."),
    ("quantitative", "medium", "6 technicians install 24 routers in 4 hours. At the same rate, how many routers can 9 technicians install in 6 hours?", ["36", "48", "54", "60"], 2, "1 router per technician-hour, so 9 x 6 = 54."),
    ("quantitative", "medium", "The average of five numbers is 18. When one number is removed, the average of the rest is 16. Which number was removed?", ["22", "24", "26", "28"], 2, "5 x 18 = 90, 4 x 16 = 64, 90 - 64 = 26."),
    ("quantitative", "easy", "Rs 10,000 earns simple interest at 8% a year. What is the interest after 3 years?", ["Rs 2,000", "Rs 2,400", "Rs 2,600", "Rs 3,000"], 1, "10,000 x 8% x 3 = 2,400."),
    ("quantitative", "hard", "A and B together finish a job in 12 days. A alone takes 20 days. How long does B take alone?", ["24 days", "28 days", "30 days", "32 days"], 2, "1/12 - 1/20 = 1/30."),
    ("quantitative", "easy", "An item costs Rs 800 and is sold at a 15% profit. What is the selling price?", ["Rs 900", "Rs 920", "Rs 935", "Rs 950"], 1, "800 x 1.15 = 920."),
    ("quantitative", "easy", "The ratio of boys to girls in a class of 40 is 3:5. How many girls are there?", ["15", "20", "25", "30"], 2, "40 x 5/8 = 25."),
    ("quantitative", "hard", "Two successive discounts of 10% and 20% equal a single discount of:", ["28%", "30%", "26%", "32%"], 0, "1 - 0.9 x 0.8 = 0.28."),
    ("quantitative", "easy", "A train covers 360 km in 4 hours. What is its average speed in km/h? (type a number)", None, 90, "360 / 4 = 90."),
    # --- logical
    ("logical", "easy", "What comes next: 3, 6, 12, 24, ?", ["36", "42", "48", "54"], 2, "Each term doubles."),
    ("logical", "easy", "All routers are devices. Some devices are wireless. Which statement must be true?", ["All routers are wireless", "Some routers are wireless", "All routers are devices", "No device is a router"], 2, "Only the first statement is certain."),
    ("logical", "easy", "Find the odd one out: Keyboard, Mouse, Scanner, Monitor", ["Keyboard", "Mouse", "Scanner", "Monitor"], 3, "The monitor is an output device; the others are input devices."),
    ("logical", "easy", "In a code, CAT is written as DBU. How is DOG written?", ["EPH", "EOH", "DPH", "FQI"], 0, "Each letter moves one place forward."),
    ("logical", "medium", "Pointing to a man, Riya says: \"He is the son of my father's only son.\" How is the man related to Riya?", ["Brother", "Nephew", "Son", "Cousin"], 1, "Her father's only son is her brother; his son is her nephew."),
    ("logical", "easy", "A is taller than B. C is shorter than B. D is taller than A. Who is the shortest?", ["A", "B", "C", "D"], 2, "D > A > B > C."),
    ("logical", "medium", "If today is Wednesday, what day will it be 45 days from today?", ["Friday", "Saturday", "Sunday", "Thursday"], 1, "45 = 6 weeks + 3 days; Wednesday + 3 = Saturday."),
    ("logical", "medium", "Which number comes next: 2, 5, 10, 17, 26, ?", ["35", "36", "37", "38"], 2, "Differences are 3, 5, 7, 9, 11."),
    ("logical", "hard", "Statements: No laptop is a printer. All printers are machines. Conclusion I: No laptop is a machine. Conclusion II: Some machines are not laptops.",
     ["Only I follows", "Only II follows", "Both follow", "Neither follows"], 1, "The printers are machines that are not laptops; I does not follow."),
    ("logical", "hard", "A clock shows 3:15. What is the angle between the hour hand and the minute hand?", ["0 degrees", "7.5 degrees", "15 degrees", "22.5 degrees"], 1, "Hour hand at 97.5 degrees, minute hand at 90 degrees."),
    # --- English
    ("english", "easy", "Choose the correctly spelt word.", ["Accomodate", "Acommodate", "Accommodate", "Acomodate"], 2, ""),
    ("english", "easy", "Choose the correct option: \"She ___ working here since 2021.\"", ["is", "has been", "was", "have been"], 1, "Present perfect continuous with 'since'."),
    ("english", "easy", "Choose the word closest in meaning to \"concise\".", ["Brief", "Detailed", "Unclear", "Lengthy"], 0, ""),
    ("english", "medium", "Choose the correct sentence.", ["Each of the engineers have a laptop.", "Each of the engineers has a laptop.", "Each of the engineer have a laptop.", "Each of engineers has laptop."], 1, "'Each' takes a singular verb."),
    ("english", "easy", "Choose the opposite of \"reluctant\".", ["Unwilling", "Eager", "Hesitant", "Slow"], 1, ""),
    ("english", "medium", "Fill in the blank: \"Please reply ___ the earliest.\"", ["on", "in", "at", "by"], 2, "'At the earliest' is the fixed phrase."),
    ("english", "easy", "Which is the most professional way to open an email to a client you haven't met?", ["Hey buddy,", "Dear Mr. Sharma,", "Yo,", "Hi dear,"], 1, ""),
    ("english", "medium", "Choose the correctly punctuated sentence.", ["Its a great product, and it's price is fair.", "It's a great product, and its price is fair.",
                                                                              "Its a great product and its price is fair.", "It's a great product, and it's price is fair."], 1, "It's = it is; its = belonging to it."),
    ("english", "easy", "To \"call off\" a meeting means to:", ["Start it", "Postpone it", "Cancel it", "Shorten it"], 2, ""),
    ("english", "medium", "Choose the passive form of: \"The technician repaired the server.\"", ["The server is repaired by the technician.", "The server was repaired by the technician.",
                                                                                                  "The server has repaired the technician.", "The server was repairing by the technician."], 1, ""),
    # --- IT hardware
    ("it_hardware", "easy", "Which component temporarily stores the data the CPU is actively using?", ["Hard disk", "RAM", "ROM", "Power supply"], 1, "RAM is working memory."),
    ("it_hardware", "easy", "Which port is commonly used to connect a modern monitor carrying both video and audio?", ["VGA", "HDMI", "PS/2", "RJ-45"], 1, ""),
    ("it_hardware", "easy", "What does SSD stand for?", ["Solid State Drive", "System Storage Device", "Serial Speed Disk", "Secure Storage Drive"], 0, ""),
    ("it_hardware", "medium", "A desktop powers on, shows no display and beeps repeatedly. What is the most sensible first thing to check?", ["The keyboard cable", "Whether the RAM is seated properly", "The mouse driver", "The printer queue"], 1, "Repeated beeps at power-on usually point to memory."),
    ("it_hardware", "medium", "Which RAID level mirrors the same data across two disks?", ["RAID 0", "RAID 1", "RAID 5", "RAID 6"], 1, "RAID 1 is mirroring."),
    ("it_hardware", "easy", "What is the main purpose of a UPS?", ["Increase internet speed", "Provide backup power and protect against power fluctuations", "Cool the server", "Store backups"], 1, ""),
    ("it_hardware", "easy", "Which cable is standard for a wired Ethernet connection to a PC?", ["RJ-11 telephone cable", "Cat6 cable with RJ-45 connectors", "HDMI cable", "USB-C cable"], 1, ""),
    ("it_hardware", "medium", "What does POST mean when a computer starts?", ["Power-On Self-Test", "Primary Operating System Task", "Port Output Signal Test", "Power Output Supply Test"], 0, ""),
    ("it_hardware", "easy", "Which is a typical sign of a failing hard disk?", ["Clicking noises and slow file access", "A brighter display", "A faster boot", "Louder speakers"], 0, ""),
    ("it_hardware", "medium", "What does thermal paste between a CPU and its heatsink do?", ["Insulates electrically, nothing more", "Improves heat transfer by filling microscopic gaps",
                                                                                            "Holds the CPU in place", "Increases the clock speed"], 1, ""),
    ("it_hardware", "medium", "Which address identifies a network card at the hardware level?", ["IP address", "MAC address", "DNS name", "Gateway address"], 1, ""),
    # --- sales awareness
    ("sales_awareness", "easy", "A customer says your price is too high. What is the best first response?", ["Offer the biggest discount at once", "Ask what they are comparing it with and what matters most to them",
                                                                                                        "End the call", "Say the competitor's product is bad"], 1, ""),
    ("sales_awareness", "easy", "What is a \"lead\" in sales?", ["A closed deal", "A potential customer who may be interested", "An invoice", "A product feature"], 1, ""),
    ("sales_awareness", "easy", "Which is an open-ended question?", ["Do you need a laptop?", "Is your budget above Rs 1 lakh?", "What challenges do you face with your current systems?", "Will you buy today?"], 2, ""),
    ("sales_awareness", "easy", "In B2B IT sales, who is usually the decision maker?", ["Any employee who uses the product", "The person with the authority and budget to approve the purchase",
                                                                                         "The delivery person", "The competitor"], 1, ""),
    ("sales_awareness", "easy", "What does \"upselling\" mean?", ["Selling to a new customer", "Persuading a customer to buy a higher-value version or an add-on", "Reducing the price", "Taking back a product"], 1, ""),
    ("sales_awareness", "medium", "After a demo the client says \"Let me think about it.\" What is the best next step?", ["Stop following up", "Agree a specific follow-up date and ask what is holding them back",
                                                                                                                     "Send ten reminders the same day", "Cut the price by half"], 1, ""),
    ("sales_awareness", "easy", "What is a sales pipeline?", ["The opportunities at each stage before closing", "A delivery route", "The finance approval process", "A product catalogue"], 0, ""),
    ("sales_awareness", "medium", "Which metric best shows how many proposals turn into orders?", ["Website visits", "Conversion rate", "Number of emails sent", "Office hours"], 1, ""),
    ("sales_awareness", "medium", "A customer urgently needs 50 laptops but you have 30 in stock. What should you do?", ["Promise all 50 tomorrow anyway", "Say so honestly: offer 30 now and a firm date for the rest, or alternatives",
                                                                                                                    "Ignore the request", "Cancel the order"], 1, ""),
    # --- computer basics
    ("computer_basics", "easy", "Which shortcut copies selected text in Windows?", ["Ctrl + V", "Ctrl + C", "Ctrl + X", "Ctrl + Z"], 1, ""),
    ("computer_basics", "easy", "Which Excel function adds up a range of cells?", ["COUNT", "SUM", "AVERAGE", "MAX"], 1, ""),
    ("computer_basics", "easy", "Which file extension is an Excel workbook?", [".docx", ".xlsx", ".pptx", ".pdf"], 1, ""),
    ("computer_basics", "easy", "What is phishing?", ["Fixing network cables", "Tricking people into revealing passwords or data, usually with fake emails", "Backing up files", "Speeding up a computer"], 1, ""),
    ("computer_basics", "medium", "What does VLOOKUP do in Excel?", ["Finds a value in the first column of a range and returns a value from another column in the same row",
                                                                      "Sorts data", "Draws a chart", "Counts blank cells"], 0, ""),
    ("computer_basics", "easy", "Which of these is an operating system?", ["Google Chrome", "Windows 11", "Microsoft Word", "Zoom"], 1, ""),
    ("computer_basics", "medium", "What is the safest way to share the password of a protected file with a colleague?", ["Put it in the same email", "Share it through a different channel, such as a phone call",
                                                                                                                       "Post it in a group chat", "Write it in the file name"], 1, ""),
    ("computer_basics", "medium", "Which formula counts the cells in A1:A10 that contain the text Done?", ['=COUNTIF(A1:A10,"Done")', '=SUM(A1:A10,"Done")', '=COUNT(A1:A10,"Done")', '=IF(A1:A10="Done")'], 0, ""),
]


def seed(s, org_id: str, user_id: str | None) -> int:
    have = {t for (t,) in s.query(db.Question.text).filter(db.Question.org_id == org_id)}
    n = 0
    for sec, diff, text, opts, ans, expl in Q:
        if text in have:
            continue
        if opts is None:
            s.add(db.Question(org_id=org_id, section=sec, difficulty=diff, kind="numeric", text=text, options=[], answer=[float(ans)],
                              explanation=expl, tags=["starter"], created_by=user_id))
        else:
            s.add(db.Question(org_id=org_id, section=sec, difficulty=diff, kind="single", text=text, options=opts, answer=[ans],
                              explanation=expl, tags=["starter"], created_by=user_id))
        n += 1
    return n
