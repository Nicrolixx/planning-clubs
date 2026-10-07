# Planning des clubs (Google Sheets publie) -> fichier texte compact lu par le monde VRChat (Hall des Clubs).
# Une ligne par event, heure de Paris (colonne "CET" du tableur), jour de Paris (les events apres minuit passent au
# jour suivant) :  jour|HH:MM|duree en minutes|type|#couleur|Nom
#   jour : 0 = lundi ... 6 = dimanche ; type : H hebdo, B une semaine sur deux, M mensuel, V date variable.
#   Les clubs "en pause" (bordure rose) et "en fermeture" (bordure rouge) sont ignores.
# Usage : python horaires_clubs.py <fichier de sortie> [identifiant du tableur]
import html, re, sys, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SHEET = sys.argv[2] if len(sys.argv) > 2 else "1c-Du5Gk-MJHlrNRMDie2uen_I7ja0CR3GR4yoUV-GTU"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BORDER_TYPE = {"#000000": "H", "#ffff00": "B", "#00ff00": "M", "#00ffff": "V", "#ff00ff": None, "#ff0000": None}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (planning FBT LAB)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


class Grid(HTMLParser):
    """Tableau HTML -> grille (lignes x colonnes) en tenant compte des cellules fusionnees."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.span = [], None, None, {}
        self.col = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row, self.col = [], 0
        elif tag == "td" and self.row is not None:
            r = len(self.rows)
            while (r, self.col) in self.span:
                self.row.append(self.span[(r, self.col)]); self.col += 1
            self.cell = {"cls": a.get("class", ""), "rows": int(a.get("rowspan", "1")), "cols": int(a.get("colspan", "1")), "text": "", "top": r, "c": self.col}

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            c, r = self.cell, len(self.rows)
            for dc in range(c["cols"]):
                self.row.append(c)
                for dr in range(1, c["rows"]):
                    self.span[(r + dr, self.col)] = {"cls": c["cls"], "rows": 0, "cols": 1, "text": "", "top": c["top"], "c": c["c"]}
                self.col += 1
            self.cell = None
        elif tag == "tr" and self.row is not None:
            r = len(self.rows)
            while (r, self.col) in self.span:
                self.row.append(self.span[(r, self.col)]); self.col += 1
            self.rows.append(self.row)
            self.row = None


def readable(hexcol):
    """Couleur du club eclaircie si besoin : lisible sur le fond sombre des panneaux."""
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    for _ in range(12):
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        if lum >= 0.42:
            break
        r, g, b = (int(c + (255 - c) * 0.18) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def parse_time(t):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$", t, re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3).upper()
    return (h + (12 if ap == "PM" else 0)) * 60 + mi


def gids():
    view = fetch("https://docs.google.com/spreadsheets/d/%s/htmlview" % SHEET)
    found = dict(re.findall(r'\{name: "([^"]+)"[^}]*?gid: "(\d+)"', view))
    return [(d, found[d]) for d in DAYS if d in found]


def day_events(day_index, gid):
    page = fetch("https://docs.google.com/spreadsheets/d/%s/htmlview/sheet?headers=false&gid=%s" % (SHEET, gid))
    css = {k: v for k, v in re.findall(r"\.ritz \.waffle \.(s\d+)\{([^}]*)\}", page)}
    g = Grid()
    g.feed(page)
    # colonnes : celle qui contient "CET" donne l'heure de Paris, les clubs sont a droite de "EST"
    cet_col = clubs_from = None
    for row in g.rows:
        for i, c in enumerate(row):
            t = c["text"].strip()
            if t == "CET": cet_col = i
            if t == "EST": clubs_from = i + 1
        if cet_col is not None:
            break
    if cet_col is None:
        return []
    events, shift, prev = [], 0, None
    for r, row in enumerate(g.rows):
        if cet_col >= len(row):
            continue
        t = parse_time(row[cet_col]["text"])
        if t is None:
            continue
        if prev is not None and t < prev:
            shift = 1                     # apres minuit (Paris) : jour suivant
        prev = t
        for c in row[clubs_from:]:
            name = html.unescape(c["text"]).strip()
            if not name or c["top"] != r or name in ("-", "..."):
                continue
            if len(name) > 40 or re.search(r"\d{1,2}(:\d{2})?\s*[ap]m", name, re.I):
                continue                  # note glissee dans une case (horaire precise, remarque), pas un club
            st = css.get(c["cls"], "")
            b = re.search(r"border-bottom:\s*\d+px\s+\w+\s+(#[0-9a-fA-F]{6})", st)
            kind = BORDER_TYPE.get(b.group(1).lower(), "H") if b else "H"
            if kind is None:
                continue                  # en pause / en fermeture
            bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", st)
            color = readable(bg.group(1).lower() if bg else "#ff2a99")
            events.append(((day_index + shift) % 7, t, max(30, c["rows"] * 30), kind, color, name.replace("|", "/")))
    return events


def main():
    out = sys.argv[1]
    ev = []
    for i, (day, gid) in enumerate(gids()):
        ev += day_events(DAYS.index(day), gid)
    if not ev:
        raise SystemExit("aucun event lu : tableur inaccessible ou format change")
    ev.sort(key=lambda e: (e[0], e[1], e[5].lower()))
    lines = ["# Planning des clubs (heure de Paris)",
             "# jour(0=lundi)|HH:MM|duree min|type(H hebdo, B 1 sem/2, M mensuel, V variable)|couleur|Nom"]
    for d, t, dur, k, col, name in ev:
        lines.append("%d|%02d:%02d|%d|%s|%s|%s" % (d, t // 60, t % 60, dur, k, col, name))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("ok %d events -> %s" % (len(ev), out))


if __name__ == "__main__":
    main()
