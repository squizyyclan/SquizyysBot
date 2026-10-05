# ⛏️ Clan-Bot für Minecraft-Clans

Verleih-System, Server-Setup per Befehl, Join-to-Create, Tickets, Willkommen und Moderation in einem Bot.

## Installation

1. **Bot anlegen:** https://discord.com/developers/applications → *New Application* → *Bot* → Token kopieren.
2. Unter *Bot → Privileged Gateway Intents* **Server Members Intent** aktivieren.
3. **Einladen:** *OAuth2 → URL Generator* → Scopes `bot` + `applications.commands`, Berechtigung **Administrator** (am einfachsten).
4. Lokal starten (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   cp .env.example .env     # Token und GUILD_ID eintragen
   python bot.py
   ```
5. In Discord: Bot-Rolle in den Servereinstellungen **ganz nach oben** ziehen, dann **`/setup`** ausführen.

> Beim Hosten (Railway, VPS …) muss die Datei `clanbot.db` auf einem **persistenten Volume** liegen, sonst gehen Katalog und Leihen bei jedem Neustart verloren.

## Was `/setup` macht (und beim erneuten Ausführen „perfektioniert“)

- Legt Rollen an: Clan-Leitung, Offizier, Verleiher, Mitglied, Rekrut, Leiher (inkl. Reihenfolge)
- Legt Kategorien/Kanäle an: Info, Clan, **Leihhaus**, Voice, Team, Tickets
- **Leihhaus ist nur sichtbar** für Leiher, Verleiher, Offiziere und Leitung
- Setzt alle Berechtigungen korrekt und repariert sie bei jedem Aufruf (Rechte, Themen, Kategorien)
- Postet Regeln, Willkommen, Rollen-Button, Ticket-Panel, Leih-Infos und den Katalog
- Vorhandene Kanäle/Rollen mit gleichem Namen werden übernommen, nichts wird doppelt angelegt

Namen, Farben und Layout änderst du in `config.py`.

## Befehle

| Bereich | Befehl | Wer |
|---|---|---|
| Setup | `/setup` | Admin |
| Katalog | `/item hinzufuegen`, `/item bestand`, `/item entfernen` | Team |
| Katalog | `/item liste` | alle |
| Leihen | `/leihen anfragen`, `/leihen meine` | Leiher |
| Leihen | `/leihen aktiv`, `/leihen rueckgabe`, `/leihen verlaengern` | Team |
| Rolle | `/leiher hinzufuegen`, `/leiher entfernen` | Team |
| Voice | `/voice name`, `limit`, `sperren`, `freigeben`, `erlauben` | Raum-Besitzer |
| Sonstiges | `/ankuendigung` | Leitung/Offiziere |
| Moderation | `/clear`, `/timeout`, `/kick`, `/ban` | mit Berechtigung |

## Ablauf einer Leihe

1. Person holt sich per Button die **Leiher-Rolle** (Kanal 🎭-rollen) – das Leihhaus wird sichtbar.
2. `/leihen anfragen` (Item per Autovervollständigung, Menge, Tage) → Anfrage landet im Team-Kanal.
3. Verleiher klickt **Genehmigen / Ablehnen** → Leiher bekommt eine DM, Katalog und Log aktualisieren sich.
4. 24 h vor Fälligkeit und bei Überfälligkeit erinnert der Bot automatisch.
5. Rückgabe per Button oder `/leihen rueckgabe`.

## Join to Create

Wer den Kanal **➕ Raum erstellen** betritt, bekommt einen eigenen Raum, in den er verschoben wird. Ist der Raum leer, wird er gelöscht.

## Deployment: GitHub + Railway

1. Ordner als **privates** GitHub-Repo pushen (`.env` und `*.db` sind per `.gitignore` ausgeschlossen).
2. Railway → *New Project* → *Deploy from GitHub repo* → Repo wählen. Der Start läuft über die `Procfile` (`worker: python bot.py`).
3. Im Service unter *Variables*: `DISCORD_TOKEN`, `GUILD_ID` (deine Server-ID), `DB_PATH=/data/clanbot.db` und am besten ein eigenes `SESSION_SECRET` (beliebiger langer Zufallstext für die Website-Logins) setzen.
4. Im Service *Settings → Volumes* (oder Rechtsklick auf den Service → *Attach Volume*) ein Volume mit Mount-Pfad `/data` anlegen, damit Katalog und Leihen Neustarts überstehen.
5. Deployen. In den Logs erscheint `Eingeloggt als …`. Jeder Push auf GitHub deployt automatisch neu.


## Nur ein Server

Der Bot läuft ausschließlich auf dem Server aus `GUILD_ID`: Slash-Commands werden nur dort registriert, Befehle von anderen Servern werden abgelehnt, und der Bot verlässt fremde Server automatisch.
Die Server-ID bekommst du so: Discord → Einstellungen → Erweitert → *Entwicklermodus* an → Rechtsklick auf den Server → *Server-ID kopieren*.


## Website: OPSUCHT-Bereiche

- **AH** und **Markt** zeigen Karten; ein Klick öffnet eine eigene Seite (`#ah/<id>`, `#markt/<item>`), die auch per Link teilbar ist.
- Spieler (Verkäufer, Bieter) werden als **Name** angezeigt. Die UUID wird serverseitig über Crafthead/Mojang/PlayerDB (Java) bzw. GeyserMC (Bedrock) aufgelöst und in der Tabelle `player_names` zwischengespeichert.
- Unter jedem OPSUCHT-Bereich steht ein Credit-Hinweis, ganz unten ein Footer mit Disclaimer.

## Impressum & Datenschutz

Die Website enthält ein Impressum (`#impressum`) und eine Datenschutzerklärung (`#datenschutz`), verlinkt im Footer. Deine Angaben kommen aus Railway-Variablen (nicht aus dem Code): `IMPRESSUM_NAME`, `IMPRESSUM_ADDRESS` (Zeilen mit `|` trennen), `IMPRESSUM_EMAIL`, optional `IMPRESSUM_PHONE`. Fehlen sie, zeigt die Seite eine Warnung. Bewerbungen werden nach 180 Tagen automatisch gelöscht.
