# Bar-Inventory — Setup-Guide

Dieses System verwaltet den Lagerbestand einer Bar mit automatisierten Nachbestellungen über Algorand-Escrow-Verträge. Der Guide führt euch Schritt für Schritt durch die lokale Einrichtung.

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#1-voraussetzungen)
2. [Projekt herunterladen](#2-projekt-herunterladen)
3. [Algorand LocalNet starten](#3-algorand-localnet-starten)
4. [Backend einrichten](#4-backend-einrichten)
5. [Frontend einrichten](#5-frontend-einrichten)
6. [Datenbank befüllen](#6-datenbank-befüllen)
7. [App starten — Kurzübersicht](#7-app-starten--kurzübersicht)
8. [Optionale Features](#8-optionale-features)
9. [Ports & URLs](#9-ports--urls)
10. [Häufige Fehler](#10-häufige-fehler)

---

## 1. Voraussetzungen

Folgende Tools müssen installiert sein, bevor ihr startet:

| Tool | Mindestversion | Download |
|---|---|---|
| **Python** | 3.11 | https://www.python.org/downloads/ |
| **Node.js** | 18 | https://nodejs.org/ |
| **Docker Desktop** | aktuell | https://www.docker.com/products/docker-desktop/ |
| **AlgoKit CLI** | 2.x | Anleitung unten |

### AlgoKit installieren

```powershell
# Windows (PowerShell als Administrator)
winget install AlgoFoundation.AlgoKit

# Oder via pip
pip install algokit
```

Nach der Installation prüfen:

```powershell
algokit --version
docker --version
python --version
node --version
```

---

## 2. Projekt herunterladen

```powershell
# Repository klonen (oder ZIP entpacken)
git clone <repo-url>
cd x402
```

Die Projektstruktur sieht so aus:

```
x402/
├── backend/          # FastAPI-Server (Python)
├── frontend/         # React-App (Node.js)
├── projects/         # Algorand Smart Contract
├── seed.py           # Demodaten einspielen
├── excel_import.py   # Import aus Excel
└── SETUP.md          # Diese Datei
```

---

## 3. Algorand LocalNet starten

Das System nutzt eine lokale Algorand-Blockchain (LocalNet) für die Escrow-Funktionalität. Docker muss laufen.

```powershell
# LocalNet starten
algokit localnet start

# Status prüfen (sollte "Running" zeigen)
algokit localnet status
```

> **Hinweis:** Docker Desktop muss im Hintergrund laufen, sonst schlägt dieser Schritt fehl.

### Smart Contract deployen

Der Escrow-Vertrag muss einmalig auf LocalNet deployt werden:

```powershell
cd projects/bar-inventory
algokit project run build
algokit project deploy localnet
cd ../..
```

---

## 4. Backend einrichten

### Python-Umgebung erstellen

```powershell
# Virtuelle Umgebung anlegen
python -m venv .venv

# Aktivieren (PowerShell)
.venv\Scripts\Activate.ps1

# Wenn PowerShell-Skripte blockiert sind:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Abhängigkeiten installieren

```powershell
pip install -r backend/requirements.txt
```

### Backend starten

```powershell
uvicorn backend.main:app --reload
```

Der Server läuft unter **http://localhost:8000**.  
Die interaktive API-Dokumentation ist unter http://localhost:8000/docs erreichbar.

---

## 5. Frontend einrichten

In einem **neuen Terminal-Fenster** (das Backend muss weiter laufen):

```powershell
cd frontend
npm install
npm run dev
```

Die App öffnet sich unter **http://localhost:5173**.

---

## 6. Datenbank befüllen

Beim ersten Start ist die Datenbank leer. Es gibt drei Möglichkeiten, Daten einzuspielen:

### Option A — Demo-Daten (empfohlen zum Testen)

Backend muss laufen. Im Root-Verzeichnis:

```powershell
python seed.py
```

Dies erstellt:
- 3 Lieferanten (The Gin House, Alpine Brewery, Metro Wholesale)
- 4 Produkte (Gin, Aperol, Pilsner, Tonic Water)
- Lieferantenkataloge mit unterschiedlichen Preisen
- Lagerbestände + 30 Tage Verkaufshistorie (für Vorhersagen)
- Budget: 100 ALGO

### Option B — Excel-Import

```powershell
# Vorlage generieren
python excel_import.py --template
# → erzeugt inventory_template.xlsx

# Ausgefüllte Datei importieren
python excel_import.py meine_daten.xlsx
```

Die Excel-Datei unterstützt diese Tabellenblätter (alle optional):
`Suppliers`, `Products`, `Stock`, `Catalog`, `Budget`

### Option C — Manuell über die UI

Unter **Suppliers** und **Inventory** können Lieferanten, Produkte und Lagerbestände direkt in der App angelegt werden.

---

## 7. App starten — Kurzübersicht

Bei jedem Start der Anwendung werden diese Schritte benötigt:

```
Terminal 1:  algokit localnet start
Terminal 2:  uvicorn backend.main:app --reload        (im Root-Verzeichnis, .venv aktiv)
Terminal 3:  cd frontend && npm run dev
```

Dann im Browser: **http://localhost:5173**

---

## 8. Optionale Features

### KI-Agent (Auto-buy mit Claude)

Der Auto-buy-Modus "KI-Agent" nutzt Claude Haiku, um automatisch den besten Lieferanten auszuwählen. Dafür wird ein Anthropic-API-Key benötigt:

1. Account anlegen unter https://console.anthropic.com
2. API-Key erstellen
3. Vor dem Backend-Start setzen:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uvicorn backend.main:app --reload
```

> Ohne API-Key fällt der KI-Agent auf den günstigsten Lieferanten zurück — die App läuft trotzdem.

### Auto-buy konfigurieren

Im **Inventory-Tab** gibt es die "Auto-buy"-Sektion. Pro Produkt kann eingestellt werden:

- **Aus** — keine automatische Nachbestellung
- **Fixierter Lieferant** — bestellt immer beim gewählten Lieferanten nach
- **KI-Agent** — Claude analysiert Preise, Bewertungen und Budget und trifft die Entscheidung

> **Wichtig:** Der gewählte Lieferant muss das Produkt in seinem Katalog haben (⚠-Symbol zeigt Konflikte an).

### Square POS Integration (optional)

Für Live-Verkaufsdaten aus Square:

1. Kostenlosen Developer-Account anlegen: https://developer.squareup.com
2. Sandbox Access Token kopieren
3. Import ausführen:

```powershell
$env:SQUARE_TOKEN = "EAAAl..."
python square_import.py
```

Für Live-Webhooks (automatische Lagerreduktion bei Square-Verkäufen) wird zusätzlich ngrok benötigt:

```powershell
# ngrok installieren: https://ngrok.com
ngrok http 8000
# Die ngrok-URL im Square Developer Dashboard als Webhook-Endpoint eintragen
```

---

## 9. Ports & URLs

| Service | URL | Beschreibung |
|---|---|---|
| Frontend | http://localhost:5173 | Die Bar-Inventory-App |
| Backend API | http://localhost:8000 | FastAPI-Server |
| API-Dokumentation | http://localhost:8000/docs | Interaktive API-Übersicht |
| Algorand LocalNet | http://localhost:4001 | algod (intern) |
| Blockchain Explorer | https://lora.algokit.io/localnet | Transaktionen ansehen |

---

## 10. Häufige Fehler

### `uvicorn: command not found`
Die virtuelle Umgebung ist nicht aktiviert.
```powershell
.venv\Scripts\Activate.ps1
```

### `algokit localnet start` schlägt fehl
Docker Desktop läuft nicht. Docker starten und erneut versuchen.

### `500 Internal Server Error` beim ersten Start
Die Datenbank-Tabellen fehlen noch oder sind veraltet. Das Backend legt sie beim Start automatisch an. Falls das Problem nach einem Schema-Update auftritt:
```powershell
python migrate_db.py
```

### Leere Predictions-/Analytics-Seite
Es gibt noch keine Verkaufshistorie. Demo-Daten einspielen:
```powershell
python seed.py
```

### Auto-buy bleibt auf "pending" stecken
Mögliche Ursachen:
- **LocalNet läuft nicht** → `algokit localnet start`
- **Lieferant hat Produkt nicht im Katalog** → im Inventory-Tab prüfen (⚠-Symbol)
- **Budget zu niedrig** → im Inventory-Tab Budget erhöhen
- **KI-Modus ohne API-Key** → fällt automatisch auf günstigsten Lieferanten zurück

### Port 8000 bereits belegt
```powershell
uvicorn backend.main:app --reload --port 8001
```
Dann in `frontend/src/App.jsx` Zeile 7 anpassen: `const API = 'http://localhost:8001'`

---

## Schnellstart-Checkliste

```
[ ] Docker Desktop läuft
[ ] algokit localnet start       → grüner Status
[ ] .venv aktiviert
[ ] uvicorn backend.main:app --reload   → "Application startup complete"
[ ] cd frontend && npm run dev   → "Local: http://localhost:5173"
[ ] python seed.py               → "Done!"
[ ] Browser: http://localhost:5173
```
