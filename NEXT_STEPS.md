# Bar-Inventory — Status & Next Steps

## Was das Programm gerade kann

Ein vollständiges Bar-Inventory-System auf Algorand, das den gesamten Procurement-Zyklus abbildet:

**Inventory & Lager**
- Lagerbestand pro Produkt mit Meldebestand und Nachbestellmenge
- Verkauf simulieren ("Sell 1") — Bestand fällt, Regel-Engine schlägt automatisch Nachbestellung vor
- Aktivitäts-Log mit allen Ein- und Ausgängen

**Bestellungen & Blockchain**
- Vollständiger Order-Lifecycle: `PENDING → FUNDED → DELIVERED → RELEASED`
- Jede Bestellung wird als Algorand-Escrow-Vertrag on-chain abgewickelt (ARC4)
- Lieferant erhält Zahlung erst nach Bestätigung der Lieferung (confirm_delivery → release)
- Audit-Trail pro Bestellung mit klickbaren Transaktions-Links (Lora Explorer)
- Lieferantenbewertung (1–5 Sterne) nach Abschluss

**Lieferanten & Preise**
- Mehrere Lieferanten mit je eigenem Katalog und unterschiedlichen Preisen
- Budgetkontrolle — Nachbestellung wird bei Budgetüberschreitung geblockt
- Bewertungsaggregation pro Lieferant

**Auto-buy**
- Pro Produkt aktivierbar: fällt Bestand unter Meldebestand, wird sofort ein Escrow eröffnet
- Modus 1: Fixierter Lieferant (manuell gewählt)
- Modus 2: KI-Agent — Claude Haiku vergleicht Angebote (Preis, Bewertung, Mindestmenge, Budget) und wählt eigenständig

**Analytics & Vorhersagen**
- KPI-Dashboard: Bestellungen, aktive Escrows, Gesamtausgaben, Budget-Auslastung
- Verbrauchsgeschwindigkeit (7-Tage / 30-Tage Velocity)
- Stockout-Vorhersage: "In X Tagen aufgebraucht", Traffic-Light-Status (kritisch / Warnung / OK)
- Günstigster Lieferant + projizierte Monatskosten pro Produkt

**Zeitsimulation**
- "Skip 1 Day"-Button: simuliert einen Verkaufstag basierend auf historischer Velocity (±30 % Rauschen)
- Dekrementiert Bestand, schreibt Sale-Events, triggert Regel-Engine + Auto-buy
- Reset löscht alle simulierten Events

**Datenbefüllung**
- `seed.py`: Demo-Daten mit 30-Tage Verkaufshistorie
- Excel-Import (flexible Spaltenerkennung, DE/EN, Template-Generator)
- Square POS Integration: Katalog-Import + Live-Webhooks (Verkauf → Lagerreduktion)

---

## Next Steps

### 1. Bugs finden & fixen

- **Zeitsimulation überschreibt reale Daten:** `SaleEvent`-Einträge aus der Simulation und aus echten Verkäufen landen in derselben Tabelle. Die Velocity-Berechnung in Analytics zieht beides zusammen, was die Vorhersagen verzerrt. Simulierte Events sollten entweder markiert oder bei Predictions herausgefiltert werden.
- **Auto-buy Race Condition:** Wenn zwei Verkäufe gleichzeitig eintreffen und beide die Regel-Engine triggern, könnten zwei PENDING-Orders für dasselbe Produkt entstehen (kurzes Zeitfenster zwischen `existing`-Check und `INSERT`). Datenbank-Unique-Constraint oder explizites Locking nötig.
- **Budget-Berechnung bei schnellen Mehrfachbestellungen:** `_budget_spent()` liest committed Orders — wird Auto-buy mehrfach schnell hintereinander getriggert (Simulation), kann der Budgetcheck denselben verbleibenden Betrag mehrfach freigeben.
- **Simulation Reset löscht keine Auto-buy-Orders:** Nach Reset bleiben FUNDED/PENDING Orders aus der Simulation bestehen und verzerren Analytics.
- **Frontend zeigt alten Stock-Stand nach Fehler:** Wenn ein API-Call fehlschlägt (z. B. Blockchain down), bleibt der angezeigte Bestand veraltet. Seite muss auch bei Fehler refreshen.

---

### 2. UI fixen

- **Responsive Design fehlt** — die App ist aktuell nur auf Desktop nutzbar; Tabellenzeilen brechen auf kleinen Bildschirmen. Tailwind-Breakpoints einbauen.
- **Leere Zustände verbessern** — bei leerer Datenbank (vor Seed) zeigen mehrere Tabs weiße Flächen ohne Erklärung, was zu tun ist.
- **Auto-buy Feedback fehlt** — wenn Auto-buy erfolgreich eine Order funded, gibt es kein sichtbares Signal in der UI (nur in der Orders-Liste erkennbar). Toast-Benachrichtigung oder Badge wäre besser.
- **Lieferant ohne Katalog-Eintrag wählbar** — im FundModal erscheinen Lieferanten, die das Produkt nicht im Katalog haben, ohne Warnung. Nur gültige Optionen anzeigen.
- **Orders-Tab lädt alle Bestellungen auf einmal** — bei vielen Orders wird das unübersichtlich. Paginierung oder Status-Filter (PENDING / FUNDED / abgeschlossen) einbauen.
- **Blockchain-Tab setzt Docker voraus** — wenn LocalNet nicht läuft, zeigt er nur einen Fehler. Bessere Fehlermeldung mit Hinweis auf `algokit localnet start`.

---

### 3. Zeitsimulation überarbeiten

Die aktuelle Simulation ist funktional, aber für eine überzeugende Demo zu grob:

- **Realistischere Verkaufsmuster** — heute: gleichmäßig zufällig. Besser: Wochentagsmuster (Fr/Sa deutlich mehr), Tageszeitmuster, gelegentliche Spitzentage (Events).
- **Mehrere Tage auf einmal überspringen** — ein Slider oder Eingabefeld "X Tage simulieren" statt immer einzeln klicken. Wichtig: Escrow-Transaktionen pro Tag, nicht pro Batch — sonst sieht die Chain-History unnatürlich aus.
- **Simulierte Events von echten trennen** — `SaleEvent.source`-Feld einführen (`"real"` / `"simulation"`), damit Predictions nur auf echten Daten basieren können (Toggle in der UI).
- **Ereignisse injizieren** — "Party-Modus": einmaliger Multiplikator (z. B. ×3) für einen Tag, um Stockout-Szenarien für die Demo zu provozieren.
- **Simulationsstand persistieren** — nach Browser-Reload geht der Zustand im Panel verloren. `SimulationClock` ist bereits in der DB, die UI sollte den Stand beim Laden anzeigen.
- **Datum anzeigen** — die simulierten Timestamps in der Aktivitäts-Log und den Predictions sollten als "simuliertes Datum" gekennzeichnet sein, damit man Demo und Echtbetrieb unterscheiden kann.

---

### 4. Sonstiges / Ideen

- **Alembic-Migrationen** — aktuell werden neue Spalten über `migrate_db.py` per Hand nachgezogen. Alembic würde Schema-Änderungen automatisch versionieren und anwenden.
- **Testnet-Deploy** — `service.py` unterstützt bereits `ALGORAND_NETWORK=testnet`. Nächster Schritt wäre ein echter Testnet-Wallet (via `BUYER_MNEMONIC`) und ein öffentlich erreichbares Backend (z. B. Railway, Render).
- **E-Mail / Push-Benachrichtigungen** — kritische Stockouts oder fehlgeschlagene Auto-buy-Versuche sollten aktiv kommuniziert werden, nicht nur im Dashboard sichtbar sein.
- **Multi-Venue** — aktuell gibt es genau einen Buyer-Account und eine Datenbank. Für mehrere Standorte bräuchte es Mandantenfähigkeit.
- **Authentifizierung** — die API ist aktuell komplett offen. Für echten Betrieb zumindest API-Key oder einfaches Login.
- **Preisvergleichs-Ansicht** — eine Seite, die für jedes Produkt alle Lieferanten nebeneinander mit Preis, Bewertung und letztem Lieferdatum zeigt. Aktuell nur indirekt in der Predictions-Tabelle sichtbar.
- **Barcode-Scanner** — Verkäufe per QR/Barcode erfassen statt manuell "Sell 1" zu klicken. Würde Square-Integration ersetzen können.
