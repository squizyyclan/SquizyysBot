"""Zentrale Konfiguration: Rollen und Server-Layout. Hier kannst du alles anpassen."""
 
MAX_OPEN_LOANS = 5  # max. offene/aktive Leihen pro Person
 
# key: (Name, Farbe, hoist (separat anzeigen), Berechtigungen)
ROLE_SPECS = {
    "leader": ("👑 | Clan-Leitung", 0xE74C3C, True, dict(
        manage_channels=True, manage_roles=True, kick_members=True, ban_members=True,
        moderate_members=True, manage_messages=True, mention_everyone=True)),
    "officer": ("🎖️ | Offizier", 0xE67E22, True, dict(
        kick_members=True, moderate_members=True, manage_messages=True)),
    "builder_lead": ("🚧 | Builder - Leitung", 0x1ABC9C, True, {}),
    "lender": ("Verleiher", 0xF1C40F, True, {}),
    "member": ("👤 | Mitglied", 0x2ECC71, False, {}),
    "recruit": ("🔰 | Rekrut", 0x95A5A6, False, {}),
    "borrower": ("Leiher", 0x3498DB, False, {}),
    "farmer": ("Farmer", 0x8BC34A, False, {}),
    "builder": ("Builder", 0x9B59B6, False, {}),
    "miner": ("Miner", 0x795548, False, {}),
}
# Reihenfolge von oben nach unten (für die Rollen-Hierarchie)
ROLE_ORDER = ["leader", "officer", "builder_lead", "lender", "member", "recruit", "borrower", "farmer", "builder", "miner"]
 
# True = man kann nur EINE der Rollen Farmer/Builder/Miner haben (Klick auf eine andere wechselt)
# False = man kann mehrere gleichzeitig haben
SKILL_ROLES_EXCLUSIVE = True
 
# view  = Rollen, die den Kanal sehen ("everyone" = alle)
# write = Rollen, die schreiben (Text) bzw. sprechen (Voice) dürfen
# Clan-Leitung und Offiziere dürfen immer alles.
LAYOUT = [
    dict(key="info", name="📢 INFO", view=["everyone"], write=[], channels=[
        dict(key="welcome", name="👋-willkommen", topic="Willkommen im Clan!"),
        dict(key="rules", name="📜-regeln", topic="Die Regeln unseres Clans"),
        dict(key="news", name="📰-ankündigungen", topic="Neuigkeiten und Events"),
        dict(key="roles", name="🎭-rollen", topic="Hol dir hier die Leiher-Rolle"),
        dict(key="tickets", name="🎫-bewerbung-support", topic="Bewerbung oder Hilfe? Öffne hier ein Ticket"),
    ]),
    dict(key="clan", name="⚔️ CLAN", view=["builder_lead", "member", "recruit", "lender"],
         write=["builder_lead", "member", "recruit", "lender"], channels=[
        dict(key="chat", name="💬-clan-chat", topic="Allgemeiner Chat"),
        dict(key="builds", name="🏰-builds-und-screenshots", topic="Zeigt eure Bauwerke"),
        dict(key="events", name="📅-events", topic="Clan-Events und Termine"),
        dict(key="botcmds", name="🤖-bot-befehle", topic="Hier dürfen Bot-Befehle genutzt werden"),
    ]),
    dict(key="loans", name="📦 LEIHHAUS", view=["borrower", "lender"], write=["lender"], channels=[
        dict(key="loan_info", name="📘-leih-infos", topic="So funktioniert das Leihhaus"),
        dict(key="loan_catalog", name="📦-katalog", topic="Alle verleihbaren Items und ihr Bestand"),
        dict(key="loan_requests", name="📝-anfragen", write=["borrower", "lender"],
             topic="Hier mit /leihen anfragen ein Item leihen"),
        dict(key="loan_log", name="🧾-leih-log", topic="Protokoll aller Leihen"),
    ]),
    dict(key="voice", name="🔊 VOICE", voice=True, view=["builder_lead", "member", "recruit", "lender"],
         write=["builder_lead", "member", "recruit", "lender"], channels=[
        dict(key="jtc", name="➕ Raum erstellen"),
        dict(key="lobby", name="🔊 Lobby"),
        dict(key="afk", name="💤 AFK"),
    ]),
    dict(key="staff", name="🛡️ TEAM", view=[], write=[], channels=[
        dict(key="team", name="🛡️-team-chat", topic="Nur für Leitung und Offiziere"),
        dict(key="loan_team", name="📬-verleih-team", view=["lender"], write=["lender"],
             topic="Hier landen Leih-Anfragen zur Freigabe"),
        dict(key="modlog", name="📋-mod-log", topic="Moderations-Log und Ticket-Transcripts"),
    ]),
    dict(key="tickets", name="🎫 TICKETS", view=[], write=[], channels=[]),
]
