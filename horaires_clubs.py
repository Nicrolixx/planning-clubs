# Planning des clubs (Google Sheets publie) -> fichier texte compact lu par le monde VRChat (Hall des Clubs),
# + planche des logos des clubs (icones des serveurs Discord des liens d'invitation du tableur).
# Une ligne par event, heure de Paris (colonne "CET" du tableur), jour de Paris (les events apres minuit passent au
# jour suivant) :  jour|HH:MM|duree en minutes|type|#couleur|Nom|invitation|logo
#   jour : 0 = lundi ... 6 = dimanche ; type : H hebdo, B une semaine sur deux, M mensuel, V date variable.
#   invitation : discord.gg/xxx (vide si aucune) ; logo : numero de case dans logos.png (-1 = aucun).
#   Les clubs "en pause" (bordure rose) et "en fermeture" (bordure rouge) sont ignores.
# Ligne d'en-tete "#atlas|colonnes|lignes|taille|empreinte" : description de logos.png.
# Usage : python horaires_clubs.py <fichier de sortie> [identifiant du tableur] [dossier cache des logos]
#   logos.png est ecrit a cote du fichier de sortie.
import hashlib, html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from html.parser import HTMLParser

SHEET = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else "1c-Du5Gk-MJHlrNRMDie2uen_I7ja0CR3GR4yoUV-GTU"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BORDER_TYPE = {"#000000": "H", "#ffff00": "B", "#00ff00": "M", "#00ffff": "V", "#ff00ff": None, "#ff0000": None}
CELL, COLS = 128, 16
UA = "DiscordBot (https://github.com/Nicrolixx/planning-clubs, 1.0)"


def fetch(url, binary=False, ua="Mozilla/5.0 (planning FBT LAB)"):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


class Grid(HTMLParser):
    """Tableau HTML -> grille (lignes x colonnes) en tenant compte des cellules fusionnees et des liens."""

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
            self.cell = {"cls": a.get("class", ""), "rows": int(a.get("rowspan", "1")), "cols": int(a.get("colspan", "1")),
                         "text": "", "top": r, "c": self.col, "href": ""}
        elif tag == "a" and self.cell is not None and not self.cell["href"]:
            self.cell["href"] = a.get("href", "")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            c, r = self.cell, len(self.rows)
            for dc in range(c["cols"]):
                self.row.append(c)
                for dr in range(1, c["rows"]):
                    self.span[(r + dr, self.col)] = {"cls": c["cls"], "rows": 0, "cols": 1, "text": "", "top": c["top"], "c": c["c"], "href": ""}
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


def invite_code(href):
    """Lien du tableur (redirection Google) -> code d'invitation Discord, ou "" si ce n'est pas une invitation."""
    if not href:
        return ""
    h = html.unescape(href)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h).query).get("q", [h])[0]
    m = re.search(r"(?:discord\.gg|discord(?:app)?\.com/invite)/([\w-]+)", q, re.I)
    return m.group(1) if m else ""


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
            events.append(((day_index + shift) % 7, t, max(30, c["rows"] * 30), kind, color, name.replace("|", "/"), invite_code(c["href"])))
    return events


# ================================================================== logos
def discord_icon(code, cache_dir, cache):
    """Icone du serveur Discord d'une invitation (128 px), via l'API publique des invitations. Cache sur disque."""
    entry = cache.get(code, {})
    fresh = time.time() - entry.get("checked", 0) < 3 * 86400
    png = os.path.join(cache_dir, code + ".png")
    if not fresh:
        for attempt in range(3):
            try:
                req = urllib.request.Request("https://discord.com/api/v10/invites/%s" % urllib.parse.quote(code), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    g = json.load(r).get("guild") or {}
                entry = {"checked": time.time(), "guild": g.get("id", ""), "icon": g.get("icon") or "", "name": g.get("name", "")}
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = float(json.loads(e.read() or b"{}").get("retry_after", 2))
                    time.sleep(min(wait + 0.5, 30))
                    continue
                entry = {"checked": time.time(), "guild": "", "icon": "", "dead": e.code}   # invitation expiree ou invalide
                break
            except Exception:
                return png if os.path.exists(png) and entry.get("icon") else None
        time.sleep(0.4)
        if entry.get("icon") and (entry.get("icon") != cache.get(code, {}).get("icon") or not os.path.exists(png)):
            try:
                data = fetch("https://cdn.discordapp.com/icons/%s/%s.png?size=128" % (entry["guild"], entry["icon"]), binary=True, ua=UA)
                with open(png, "wb") as f:
                    f.write(data)
            except Exception:
                pass
        cache[code] = entry
    return png if entry.get("icon") and os.path.exists(png) else None


def build_atlas(codes, atlas_path, cache_dir):
    """Planche de logos ronds (16 par ligne, 128 px). Renvoie {code: numero de case} et l'en-tete #atlas."""
    from PIL import Image, ImageDraw
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "cache.json")
    cache = json.load(open(cache_file, encoding="utf-8")) if os.path.exists(cache_file) else {}
    icons = []
    for code in sorted(set(c for c in codes if c), key=str.lower):
        p = discord_icon(code, cache_dir, cache)
        if p:
            icons.append((code, p))
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)
    rows = max(1, (len(icons) + COLS - 1) // COLS)
    atlas = Image.new("RGBA", (COLS * CELL, rows * CELL), (0, 0, 0, 0))
    mask = Image.new("L", (CELL * 4, CELL * 4), 0)
    ImageDraw.Draw(mask).ellipse((6, 6, CELL * 4 - 7, CELL * 4 - 7), fill=255)
    mask = mask.resize((CELL, CELL), Image.LANCZOS)
    index = {}
    for i, (code, p) in enumerate(icons):
        try:
            im = Image.open(p).convert("RGBA").resize((CELL, CELL), Image.LANCZOS)
        except Exception:
            continue
        a = Image.new("L", (CELL, CELL), 0)
        a.paste(mask, (0, 0))
        from PIL import ImageChops
        im.putalpha(ImageChops.multiply(im.getchannel("A"), a))
        atlas.alpha_composite(im, ((i % COLS) * CELL, (i // COLS) * CELL))
        index[code] = i
    buf = io.BytesIO()
    atlas.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    old = open(atlas_path, "rb").read() if os.path.exists(atlas_path) else b""
    if data != old:
        with open(atlas_path, "wb") as f:
            f.write(data)
    digest = hashlib.sha1(data).hexdigest()[:10]
    return index, "#atlas|%d|%d|%d|%s" % (COLS, rows, CELL, digest)


def main():
    out = sys.argv[1]
    cache_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(out)), "logos_cache")
    ev = []
    for i, (day, gid) in enumerate(gids()):
        ev += day_events(DAYS.index(day), gid)
    if not ev:
        raise SystemExit("aucun event lu : tableur inaccessible ou format change")
    # un meme club garde la meme invitation partout (certaines cases n'ont pas le lien)
    by_name = {}
    for e in ev:
        if e[6]:
            by_name.setdefault(e[5].lower(), e[6])
    ev = [e[:6] + (e[6] or by_name.get(e[5].lower(), ""),) for e in ev]
    index, atlas_line = build_atlas([e[6] for e in ev], os.path.join(os.path.dirname(os.path.abspath(out)), "logos.png"), cache_dir)
    ev.sort(key=lambda e: (e[0], e[1], e[5].lower()))
    lines = ["# Planning des clubs (heure de Paris)",
             "# jour(0=lundi)|HH:MM|duree min|type(H hebdo, B 1 sem/2, M mensuel, V variable)|couleur|Nom|invitation|logo",
             atlas_line]
    for d, t, dur, k, col, name, code in ev:
        lines.append("%d|%02d:%02d|%d|%s|%s|%s|%s|%d" % (d, t // 60, t % 60, dur, k, col, name,
                                                           ("discord.gg/" + code) if code else "", index.get(code, -1)))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("ok %d events, %d logos -> %s" % (len(ev), len(index), out))


if __name__ == "__main__":
    main()
