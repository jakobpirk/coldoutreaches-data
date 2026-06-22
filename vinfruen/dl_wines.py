import os, urllib.request
from PIL import Image, ImageOps
from io import BytesIO

BASE = "https://impro.usercontent.one/appid/oneComWsb/domain/vinfruen.dk/media/vinfruen.dk/onewebmedia/"
OUT = os.path.join("assets", "wines")
os.makedirs(OUT, exist_ok=True)

# slug -> remote filename (unencoded; urllib will quote)
wines = {
    "bunzelt-scheurebe-halbtrocken": "Bunzelt Scheurebe halbtrocken 2018.jpg",
    "bunzelt-fraulein-paupau":       "Fraulein PauPau.jpg",
    "bunzelt-scheurebe-trocken":     "Bunzelt Scheurebe trocken 2019.jpg",
    "bunzelt-silvaner":              "Bunzelt Silvaner 2023.jpg",
    "bunzelt-traminer":              "Bunzelt Traminer 2019.jpg",
    "hart-huxelrebe":                "Hart Huxelrebe Spätlese 2022.jpg",
    "hart-riesling":                 "Hart Riesling 2011.jpg",
    "hart-scheurebe":                "Hart Scheurebe 2022.jpg",
    "hart-souvignier-gris":          "Hart Souvignier-Gris Erste Lage 2022.jpg",
    "kilian-bacchus":                "Kilian Bacchus 2021.jpg",
    "kilian-kerner":                 "Kilian Kerner 2019.jpg",
    "kilian-muller-thurgau":         "Kilian Müller-Thurgau 2019___serialized1.jpg",
    "kilian-silvaner":               "Kilian Silvaner 2018.jpg",
    "lange-cabernet-blanc":          "Lange Cabernet Blanc trocken 2018.jpg",
    "schinhammer-bacchus":           "Schinhammer Bacchus 2020.jpg",
    "schinhammer-johanniter":        "Schinhammer Johanniter 2021.jpg",
    "schinhammer-riesling":          "Schinhammer Riesling___serialized3.jpg",
    "schinhammer-rivaner":           "Schinhammer Rivaner 2021.jpg",
    "schinhammer-weissburgunder":    "Schinhammer Weissburgunder Grosse Rebe.jpg",
    "schomig-muller-thurgau":        "Schömig Müller-Thurgau 2017.jpg",
    "schomig-silvaner":              "Schömig Silvaner 2022.jpg",
    "3zeilen-blanc":                 "3 Zeilen Blanc 2016.jpg",
}

ok, fail = [], []
for slug, fname in wines.items():
    url = BASE + urllib.parse.quote(fname)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=30).read()
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
        # bottle shots are tall; cap height at 900px
        if im.height > 900:
            w = int(im.width * 900 / im.height)
            im = im.resize((w, 900), Image.LANCZOS)
        dest = os.path.join(OUT, slug + ".jpg")
        im.save(dest, "JPEG", quality=82, optimize=True)
        ok.append((slug, im.size, os.path.getsize(dest)//1024))
    except Exception as e:
        fail.append((slug, str(e)))

print("OK:", len(ok))
for s, size, kb in ok:
    print(f"  {s}: {size[0]}x{size[1]} {kb}KB")
print("FAIL:", len(fail))
for s, e in fail:
    print(f"  {s}: {e}")
