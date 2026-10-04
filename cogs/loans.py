import datetime as dt
from typing import Optional
 
import discord
from discord import app_commands
from discord.ext import commands, tasks
 
import db
from config import MAX_OPEN_LOANS
from cogs.ingame import get_ign
from utils import ensure_message, get_ch, get_role, is_staff, staff_only
 
 
def now():
    return dt.datetime.now(dt.timezone.utc)
 
 
def ts(iso_str, style="R"):
    return f"<t:{int(dt.datetime.fromisoformat(iso_str).timestamp())}:{style}>"
 
 
# ---------------------------------------------------------------- Bestand
 
async def available(item_id):
    item = await db.fetchone("SELECT stock FROM items WHERE id=?", (item_id,))
    used = await db.fetchone(
        "SELECT COALESCE(SUM(amount), 0) AS n FROM loans WHERE item_id=? AND status='active'", (item_id,))
    return (item["stock"] if item else 0) - used["n"]
 
 
async def catalog_embed(guild_id):
    items = await db.fetchall("SELECT * FROM items WHERE guild_id=? ORDER BY name", (guild_id,))
    lines = []
    for it in items:
        av = await available(it["id"])
        line = f"{'🟢' if av > 0 else '🔴'} **{it['name']}** – {av}/{it['stock']} verfügbar"
        if it["description"]:
            line += f"\n　↳ {it['description']}"
        lines.append(line)
    embed = discord.Embed(title="📦 Leih-Katalog", colour=discord.Colour.blue())
    embed.description = "\n".join(lines)[:4000] if lines else "Noch keine Items im Katalog."
    embed.set_footer(text="Leihen mit /leihen anfragen")
    return embed
 
 
async def refresh_catalog(guild):
    ch = await get_ch(guild, "loan_catalog")
    if ch:
        await ensure_message(guild, ch, "catalog", await catalog_embed(guild.id))
 
 
# ---------------------------------------------------------------- Leih-Embeds & Buttons
 
STATUS = {
    "pending": ("⏳ Offen", 0xF1C40F),
    "active": ("✅ Verliehen", 0x2ECC71),
    "denied": ("❌ Abgelehnt", 0xE74C3C),
    "returned": ("📥 Zurückgegeben", 0x95A5A6),
}
 
 
async def loan_embed(loan, footer=None):
    item = await db.fetchone("SELECT name FROM items WHERE id=?", (loan["item_id"],))
    label, colour = STATUS[loan["status"]]
    e = discord.Embed(title=f"Leihe #{loan['id']} – {label}", colour=colour)
    e.add_field(name="Item", value=f"{loan['amount']}× {item['name'] if item else '(gelöscht)'}")
    e.add_field(name="Leiher", value=f"<@{loan['user_id']}>")
    ign = await get_ign(loan["user_id"])
    if ign:
        e.add_field(name="Ingame", value=ign)
    e.add_field(name="Dauer", value=f"{loan['days']} Tage")
    if loan["due_at"]:
        e.add_field(name="Fällig", value=ts(loan["due_at"]))
    if loan["note"]:
        e.add_field(name="Notiz", value=loan["note"], inline=False)
    if footer:
        e.set_footer(text=footer)
    return e
 
 
class LoanButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"loan:(?P<action>approve|deny|return):(?P<id>\d+)"):
    LOOK = {
        "approve": ("Genehmigen", discord.ButtonStyle.success, "✅"),
        "deny": ("Ablehnen", discord.ButtonStyle.danger, "❌"),
        "return": ("Als zurückgegeben markieren", discord.ButtonStyle.primary, "📥"),
    }
 
    def __init__(self, action, loan_id):
        label, style, emoji = self.LOOK[action]
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji,
                                           custom_id=f"loan:{action}:{loan_id}"))
        self.action, self.loan_id = action, loan_id
 
    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["id"]))
 
    async def callback(self, interaction: discord.Interaction):
        if not await is_staff(interaction.user):
            return await interaction.response.send_message("Nur das Verleih-Team darf das.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        msg = await process_loan(interaction.guild, self.loan_id, self.action, interaction.user)
        await interaction.followup.send(msg, ephemeral=True)
 
 
def loan_view(loan_id, status):
    view = discord.ui.View(timeout=None)
    if status == "pending":
        view.add_item(LoanButton("approve", loan_id))
        view.add_item(LoanButton("deny", loan_id))
    elif status == "active":
        view.add_item(LoanButton("return", loan_id))
    return view
 
 
async def update_team_message(guild, loan):
    team = await get_ch(guild, "loan_team")
    if not team or not loan["message_id"]:
        return
    try:
        msg = await team.fetch_message(loan["message_id"])
        await msg.edit(embed=await loan_embed(loan), view=loan_view(loan["id"], loan["status"]))
    except discord.HTTPException:
        pass
 
 
async def process_loan(guild, loan_id, action, actor):
    loan = await db.fetchone("SELECT * FROM loans WHERE id=? AND guild_id=?", (loan_id, guild.id))
    if not loan:
        return "Leihe nicht gefunden."
    needed = {"approve": "pending", "deny": "pending", "return": "active"}[action]
    if loan["status"] != needed:
        return f"Leihe #{loan_id} hat bereits den Status '{loan['status']}'."
 
    if action == "approve":
        if await available(loan["item_id"]) < loan["amount"]:
            return "Nicht genug Bestand verfügbar."
        due = (now() + dt.timedelta(days=loan["days"])).isoformat()
        await db.execute("UPDATE loans SET status='active', due_at=?, reminded=0 WHERE id=?", (due, loan_id))
        text = f"✅ Deine Leihe #{loan_id} wurde genehmigt. Bitte zurückgeben bis {ts(due, 'F')}."
    elif action == "deny":
        await db.execute("UPDATE loans SET status='denied' WHERE id=?", (loan_id,))
        text = f"❌ Deine Leih-Anfrage #{loan_id} wurde leider abgelehnt."
    else:
        await db.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
                         (now().isoformat(), loan_id))
        text = f"📥 Danke! Leihe #{loan_id} ist als zurückgegeben eingetragen."
 
    loan = await db.fetchone("SELECT * FROM loans WHERE id=?", (loan_id,))
    await update_team_message(guild, loan)
    await refresh_catalog(guild)
    log = await get_ch(guild, "loan_log")
    if log:
        await log.send(embed=await loan_embed(loan, footer=f"Bearbeitet von {actor.display_name}"))
    member = guild.get_member(loan["user_id"])
    if member:
        try:
            await member.send(text)
        except discord.HTTPException:
            pass
    return f"Leihe #{loan_id}: erledigt."
 
 
# ---------------------------------------------------------------- Rollen-Button
 
class BorrowerRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label="Leiher-Rolle holen / abgeben", emoji="🤝",
                       style=discord.ButtonStyle.primary, custom_id="clan:toggle_borrower")
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = await get_role(interaction.guild, "borrower")
        if not role:
            return await interaction.response.send_message(
                "Die Rolle fehlt noch – ein Admin muss /setup ausführen.", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            text = "Du hast die Leiher-Rolle abgegeben."
        else:
            await interaction.user.add_roles(role)
            text = "🤝 Du bist jetzt Leiher und siehst das Leihhaus!"
        await interaction.response.send_message(text, ephemeral=True)
 
 
# ---------------------------------------------------------------- Autocomplete & Listen
 
async def item_autocomplete(interaction: discord.Interaction, current: str):
    rows = await db.fetchall(
        "SELECT name FROM items WHERE guild_id=? AND name LIKE ? ORDER BY name LIMIT 25",
        (interaction.guild_id, f"%{current}%"))
    return [app_commands.Choice(name=r["name"], value=r["name"]) for r in rows]
 
 
def loan_lines(rows):
    lines = []
    for r in rows:
        when = f"fällig {ts(r['due_at'])}" if r["due_at"] else "wartet auf Freigabe"
        lines.append(f"`#{r['id']}` {r['amount']}× **{r['item_name'] or '?'}** • <@{r['user_id']}> • {when}")
    return "\n".join(lines)[:4000] or "Keine Einträge."
 
 
LOAN_SELECT = ("SELECT l.*, i.name AS item_name FROM loans l LEFT JOIN items i ON i.id = l.item_id "
               "WHERE l.guild_id=? AND l.status IN ('pending','active')")
 
 
# ---------------------------------------------------------------- Cog
 
class Loans(commands.Cog):
    item = app_commands.Group(name="item", description="Items im Leihhaus verwalten", guild_only=True)
    leihen = app_commands.Group(name="leihen", description="Items leihen", guild_only=True)
    leiher = app_commands.Group(name="leiher", description="Leiher-Rolle verwalten", guild_only=True)
 
    def __init__(self, bot):
        self.bot = bot
 
    async def cog_load(self):
        self.bot.add_dynamic_items(LoanButton)
        self.bot.add_view(BorrowerRoleView())
        self.reminders.start()
 
    async def cog_unload(self):
        self.reminders.cancel()
 
    # ----- Items
 
    @item.command(name="hinzufuegen", description="Item zum Katalog hinzufügen (oder Bestand erhöhen)")
    @app_commands.describe(name="Name des Items", bestand="Wie viele besitzt der Clan?",
                           beschreibung="Optional: z. B. Verzauberungen")
    @staff_only()
    async def item_add(self, interaction: discord.Interaction, name: str,
                       bestand: app_commands.Range[int, 1, 100000], beschreibung: Optional[str] = None):
        row = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (interaction.guild_id, name))
        if row:
            await db.execute("UPDATE items SET stock=stock+?, description=COALESCE(?, description) WHERE id=?",
                             (bestand, beschreibung, row["id"]))
            text = f"Bestand von **{row['name']}** um {bestand} erhöht."
        else:
            await db.execute("INSERT INTO items (guild_id, name, stock, description) VALUES (?,?,?,?)",
                             (interaction.guild_id, name, bestand, beschreibung))
            text = f"**{name}** ({bestand}×) zum Katalog hinzugefügt."
        await refresh_catalog(interaction.guild)
        await interaction.response.send_message(text, ephemeral=True)
 
    @item.command(name="bestand", description="Gesamtbestand eines Items setzen")
    @app_commands.autocomplete(name=item_autocomplete)
    @staff_only()
    async def item_stock(self, interaction: discord.Interaction, name: str,
                         bestand: app_commands.Range[int, 0, 100000]):
        row = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (interaction.guild_id, name))
        if not row:
            return await interaction.response.send_message("Item nicht gefunden.", ephemeral=True)
        lent = row["stock"] - await available(row["id"])
        if bestand < lent:
            return await interaction.response.send_message(
                f"Aktuell sind {lent}× verliehen – der Bestand kann nicht darunter liegen.", ephemeral=True)
        await db.execute("UPDATE items SET stock=? WHERE id=?", (bestand, row["id"]))
        await refresh_catalog(interaction.guild)
        await interaction.response.send_message(f"Bestand von **{row['name']}** ist jetzt {bestand}.", ephemeral=True)
 
    @item.command(name="entfernen", description="Item aus dem Katalog löschen")
    @app_commands.autocomplete(name=item_autocomplete)
    @staff_only()
    async def item_remove(self, interaction: discord.Interaction, name: str):
        row = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (interaction.guild_id, name))
        if not row:
            return await interaction.response.send_message("Item nicht gefunden.", ephemeral=True)
        if row["stock"] - await available(row["id"]) > 0:
            return await interaction.response.send_message("Das Item ist noch verliehen.", ephemeral=True)
        await db.execute("DELETE FROM items WHERE id=?", (row["id"],))
        await refresh_catalog(interaction.guild)
        await interaction.response.send_message(f"**{row['name']}** wurde entfernt.", ephemeral=True)
 
    @item.command(name="liste", description="Alle Items mit Bestand anzeigen")
    async def item_list(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=await catalog_embed(interaction.guild_id), ephemeral=True)
 
    # ----- Leihen
 
    @leihen.command(name="anfragen", description="Ein Item leihen")
    @app_commands.describe(item="Welches Item?", menge="Wie viele?", tage="Für wie viele Tage?",
                           notiz="Optional: wofür brauchst du es?")
    @app_commands.autocomplete(item=item_autocomplete)
    async def request(self, interaction: discord.Interaction, item: str,
                      menge: app_commands.Range[int, 1, 1000] = 1,
                      tage: app_commands.Range[int, 1, 60] = 7, notiz: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild, member = interaction.guild, interaction.user
        role = await get_role(guild, "borrower")
        if not (role and role in member.roles) and not await is_staff(member):
            return await interaction.followup.send(
                "Du brauchst zuerst die Leiher-Rolle – hol sie dir im Kanal #🎭-rollen.")
        row = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (guild.id, item))
        if not row:
            return await interaction.followup.send("Dieses Item gibt es nicht. Nutze die Autovervollständigung.")
        if not await get_ign(member.id):
            return await interaction.followup.send("Hinterlege zuerst deinen Ingame-Namen mit `/ign setzen`.")
        open_n = (await db.fetchone(
            "SELECT COUNT(*) AS n FROM loans WHERE guild_id=? AND user_id=? AND status IN ('pending','active')",
            (guild.id, member.id)))["n"]
        if open_n >= MAX_OPEN_LOANS:
            return await interaction.followup.send(f"Du hast bereits {open_n} offene Leihen (Maximum {MAX_OPEN_LOANS}).")
        av = await available(row["id"])
        if av < menge:
            return await interaction.followup.send(f"Aktuell sind nur {av}× **{row['name']}** verfügbar.")
        team = await get_ch(guild, "loan_team")
        if not team:
            return await interaction.followup.send("Das Leihhaus ist noch nicht eingerichtet (/setup).")
 
        loan_id = await db.execute(
            "INSERT INTO loans (guild_id, user_id, item_id, amount, days, status, requested_at, note) "
            "VALUES (?,?,?,?,?,'pending',?,?)",
            (guild.id, member.id, row["id"], menge, tage, now().isoformat(), notiz))
        loan = await db.fetchone("SELECT * FROM loans WHERE id=?", (loan_id,))
        lender = await get_role(guild, "lender")
        try:
            msg = await team.send(content=lender.mention if lender else None, embed=await loan_embed(loan),
                                  view=loan_view(loan_id, "pending"),
                                  allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            await db.execute("DELETE FROM loans WHERE id=?", (loan_id,))
            return await interaction.followup.send("Anfrage konnte nicht gesendet werden. Sag einem Admin Bescheid.")
        await db.execute("UPDATE loans SET message_id=? WHERE id=?", (msg.id, loan_id))
        await interaction.followup.send(f"📨 Anfrage `#{loan_id}` ist raus – du bekommst eine DM, sobald sie bearbeitet wurde.")
 
    @leihen.command(name="meine", description="Deine offenen und aktiven Leihen")
    async def mine(self, interaction: discord.Interaction):
        rows = await db.fetchall(LOAN_SELECT + " AND l.user_id=? ORDER BY l.id",
                                 (interaction.guild_id, interaction.user.id))
        await interaction.response.send_message(
            embed=discord.Embed(title="Deine Leihen", description=loan_lines(rows)), ephemeral=True)
 
    @leihen.command(name="aktiv", description="Alle offenen und aktiven Leihen (Team)")
    @staff_only()
    async def active(self, interaction: discord.Interaction):
        rows = await db.fetchall(LOAN_SELECT + " ORDER BY l.id", (interaction.guild_id,))
        await interaction.response.send_message(
            embed=discord.Embed(title="Offene & aktive Leihen", description=loan_lines(rows)), ephemeral=True)
 
    @leihen.command(name="rueckgabe", description="Leihe als zurückgegeben markieren (Team)")
    @staff_only()
    async def give_back(self, interaction: discord.Interaction, leih_id: int):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await process_loan(interaction.guild, leih_id, "return", interaction.user))
 
    @leihen.command(name="verlaengern", description="Leihfrist verlängern (Team)")
    @staff_only()
    async def extend(self, interaction: discord.Interaction, leih_id: int, tage: app_commands.Range[int, 1, 60]):
        loan = await db.fetchone("SELECT * FROM loans WHERE id=? AND guild_id=? AND status='active'",
                                 (leih_id, interaction.guild_id))
        if not loan:
            return await interaction.response.send_message("Keine aktive Leihe mit dieser ID.", ephemeral=True)
        due = (dt.datetime.fromisoformat(loan["due_at"]) + dt.timedelta(days=tage)).isoformat()
        await db.execute("UPDATE loans SET due_at=?, reminded=0 WHERE id=?", (due, leih_id))
        loan = await db.fetchone("SELECT * FROM loans WHERE id=?", (leih_id,))
        await update_team_message(interaction.guild, loan)
        await interaction.response.send_message(f"Leihe #{leih_id} verlängert, neu fällig {ts(due)}.", ephemeral=True)
 
    # ----- Leiher-Rolle
 
    @leiher.command(name="hinzufuegen", description="Person die Leiher-Rolle geben (Team)")
    @staff_only()
    async def borrower_add(self, interaction: discord.Interaction, person: discord.Member):
        role = await get_role(interaction.guild, "borrower")
        if not role:
            return await interaction.response.send_message("Rolle fehlt – bitte /setup ausführen.", ephemeral=True)
        await person.add_roles(role)
        await interaction.response.send_message(f"{person.mention} ist jetzt Leiher.", ephemeral=True)
 
    @leiher.command(name="entfernen", description="Person die Leiher-Rolle wegnehmen (Team)")
    @staff_only()
    async def borrower_remove(self, interaction: discord.Interaction, person: discord.Member):
        role = await get_role(interaction.guild, "borrower")
        if role:
            await person.remove_roles(role)
        await interaction.response.send_message(f"{person.mention} ist kein Leiher mehr.", ephemeral=True)
 
    # ----- Erinnerungen
 
    @tasks.loop(minutes=15)
    async def reminders(self):
        t = now()
        for loan in await db.fetchall("SELECT * FROM loans WHERE status='active'"):
            guild = self.bot.get_guild(loan["guild_id"])
            if not guild:
                continue
            due = dt.datetime.fromisoformat(loan["due_at"])
            member = guild.get_member(loan["user_id"])
            if t > due and loan["reminded"] < 2:
                await db.execute("UPDATE loans SET reminded=2 WHERE id=?", (loan["id"],))
                if member:
                    try:
                        await member.send(f"⚠️ Deine Leihe #{loan['id']} ist überfällig! Bitte gib das Item zurück.")
                    except discord.HTTPException:
                        pass
                team = await get_ch(guild, "loan_team")
                if team:
                    await team.send(f"⚠️ Leihe #{loan['id']} von <@{loan['user_id']}> ist **überfällig**.",
                                    allowed_mentions=discord.AllowedMentions.none())
            elif due - t < dt.timedelta(hours=24) and loan["reminded"] < 1:
                await db.execute("UPDATE loans SET reminded=1 WHERE id=?", (loan["id"],))
                if member:
                    try:
                        await member.send(f"⏰ Deine Leihe #{loan['id']} ist {ts(loan['due_at'])} fällig.")
                    except discord.HTTPException:
                        pass
 
    @reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()
 
 
async def setup(bot):
    await bot.add_cog(Loans(bot))
 
