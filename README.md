# 1-es vonal késés monitor

Ez egy egyszerű Docker alkalmazás, ami egy weboldalon mutatja a MÁV 1-es (Budapest-Hegyeshalom) és 12-es (Oroszlány) vonalán aktuálisan késő vonatokat.

## ⚙️ Működés

* A program egy szerver-oldali gyorsítótárat (cache) használ. Az adatok 5 percenként frissülnek automatikusan.
* Az "Adatok frissítése" gomb megnyomásakor a gyorsítótár frissül, de 1 perces időlimittel van védve a túlterhelés ellen.

## 🚀 Telepítés

Az indításhoz 4 fájlra van szükség.

**Szükséges fájlok:**
* `app.py`
* `Dockerfile`
* `requirements.txt`
* `templates/index.html`

---

### 1. Image építése

Nyisson egy terminált abban a mappában, ahol a fenti fájlok vannak, és futtassa:

```bash
docker build -t mav-web-app .
```

### 2. Konténer indítása
Futtassa a konténert, és irányítsa át a portot. (A 8080-as port szabadon választható, ez lesz a szerver külső portja.)

```bash
docker run -d -p 8080:5000 --name mav-web mav-web-app
```
