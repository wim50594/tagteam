# 🏷️ MultiTag Suite v3.0

Universal annotation tool für Bilder, PDFs, Texte und Literatur (CSV/XLSX).

## Schnellstart

```bash
docker compose up --build
```

Dann im Browser öffnen: **http://localhost:3000**

## Features

- **Universeller Upload**: Bilder (PNG/JPG/GIF/WEBP/SVG), PDFs, Texte (TXT/MD), Tabellen (CSV/TSV/XLSX)
- **Ordner-Upload**: Komplette Ordnerstrukturen per Drag & Drop oder Klick hochladbar
- **Hierarchische Taxonomie**: CSV/TSV (mehrere Spalten = Hierarchieebenen) oder TXT (Zeilen, `>` als Trennzeichen)
  - Auto-Ancestor-Zuweisung: Wenn du `Logistics` wählst und es unter `Travel` liegt, werden beide Tags gesetzt
- **Multi-Annotator**: Beliebig viele Personen, Round-Robin oder Verifizierungsmodus
- **Tag-Suche**: Klick für Top-Level-Vorschläge, Tippen für Autocomplete
- **Persistenz**: Redis speichert alles, Container kann gestoppt/neugestartet werden
- **Export**: CSV (raw pro Annotator, oder merged/konsolidiert)
- **Konfliktauflösung**: Im Verifizierungsmodus werden Widersprüche angezeigt und können manuell aufgelöst werden

## Datenhaltung

```
multitag/
├── data/
│   ├── media/     ← Hochgeladene Bilder, PDFs etc. (Docker Volume)
│   └── redis/     ← Redis AOF-Persistenz (Docker Volume)
```

Beide Ordner sind Docker Volumes – Daten bleiben beim `docker compose stop/start` erhalten.

## Kubernetes

Für Kubernetes kannst du die Volumes als PersistentVolumeClaims deklarieren:

```yaml
# PVC für Media-Dateien
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: multitag-media-pvc
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 10Gi
---
# PVC für Redis
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: multitag-redis-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
```

## Taxonomie-Format

**CSV (hierarchisch)**:
```csv
Kategorie,Unterkategorie,Tag
Natur,Tiere,Hund
Natur,Tiere,Katze
Natur,Pflanzen,Baum
```

**TXT (flach oder hierarchisch mit `>`)**:
```
Natur > Tiere > Hund
Natur > Tiere > Katze
Technik > Software > Python
```

## Projekt löschen

Im Home-Screen auf "Löschen" klicken – löscht Session, Labels und alle zugehörigen Mediendateien.
