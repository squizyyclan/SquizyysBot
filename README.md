# Squizyys Desktop-App (Windows)

Eine kleine Windows-App, die die Clan-Website in einem eigenen Fenster öffnet (inkl. Discord-Login).
Änderungen an der Website erscheinen automatisch in der App, du musst sie dafür **nicht** neu bauen.

## Einrichten (einmalig)

1. Neues **öffentliches** GitHub-Repo anlegen (z. B. `squizyys-app`) und alle diese Dateien hochladen
   (auch `.github/workflows/build.yml`).
2. Repo → *Settings → Secrets and variables → Actions → Variables → New repository variable*:
   Name `SITE_URL`, Wert = Adresse deiner Website (z. B. `https://deine-seite.up.railway.app`).
3. Repo → *Settings → Actions → General → Workflow permissions* → **Read and write permissions** → Save.
4. Repo → *Actions → Windows-App bauen → Run workflow*. Nach ca. 3-5 Minuten gibt es unter *Releases* die `Squizyys-App.exe`.
5. In Railway beim Bot die Variable `APP_DOWNLOAD_URL` setzen:
   `https://github.com/DEIN-NAME/squizyys-app/releases/download/latest/Squizyys-App.exe`

## Hinweise

- Die Datei ist nicht signiert. Windows zeigt beim ersten Start „Der Computer wurde durch Windows geschützt":
  *Weitere Informationen → Trotzdem ausführen*. Das ist normal bei kostenlosen Apps ohne Zertifikat.
- Neu bauen musst du nur, wenn sich die Website-Adresse oder das Icon ändern.
