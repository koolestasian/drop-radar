"""What kind of role a posting is: its level (internship, new grad) and its track (software, quant...).

The feed filters on these, so the rules live here once. The title decides first; the stored
category / role_track only break a tie, because they are blank on most rows.
"""
import re

INTERN = re.compile(r"\b(intern(ship)?s?|co-?op)\b", re.I)
NEW_GRAD = re.compile(r"\b(new (college )?grad(uate)?s?|grads?|graduate|early careers?|entry[- ]level|university|campus|junior)\b", re.I)

# First match wins, so the order matters ("Quant Developer" is Quant, not Software).
TRACKS = [
    ("Quant", r"\b(quant|trading|trader)\b"),
    ("AI / ML / Data", r"\b(machine learning|ml|ai|data (scien|eng|analy)\w*|research scientist|nlp|llm)\b"),
    ("Hardware", r"\b(hardware|electrical|embedded|firmware|silicon|asic|fpga|mechanical)\b"),
    ("Security", r"\b(security|cyber|infosec)\b"),
    ("Product", r"\b(product|program) (manag|design)"),
    ("Design", r"\b(design|ux|ui)\b"),
    ("Software", r"\b(software|swe|developer|engineer|backend|frontend|full[- ]?stack|devops|sre|platform)\b"),
    ("Finance", r"\b(invest\w*|banking|banker|bank|finance|financial|equity|asset|wealth|fp&a|m&a|treasury|credit|risk|accounting|accountant|audit|tax|actuarial)\b"),
    ("Business", r"\b(consult\w*|strategy|business (analyst|operations|development|intelligence)|operations|marketing|sales|supply chain|logistics|hr|human resources|underwriting|insurance|project manag\w*)\b"),
]
_TRACKS = [(name, re.compile(rx, re.I)) for name, rx in TRACKS]
TRACK_NAMES = [name for name, _ in TRACKS] + ["Other"]


def level(title, category=""):
    """"intern", "new_grad" or "" (anything else). An internship wins over new grad within the same text."""
    for text in (title, category):
        if INTERN.search(text):
            return "intern"
        if NEW_GRAD.search(text):
            return "new_grad"
    return ""


def track(title, role_track=""):
    text = f"{title} {role_track}"
    return next((name for name, rx in _TRACKS if rx.search(text)), "Other")
