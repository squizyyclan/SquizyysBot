import discord
from discord import app_commands
from discord.ext import commands
 
import db
from cogs.community import SkillRoleView, TicketPanelView
from cogs.loans import BorrowerRoleView, refresh_catalog
from config import LAYOUT, ROLE_ORDER, ROLE_SPECS
from utils import _norm, ensure_message, find_role, get_role
 
RULES_TEXT = (
    "1️⃣ Sei respektvoll – kein Mobbing, keine Beleidigungen.\n"
    "2️⃣ Kein Griefing, Stehlen oder Cheaten – weder im Clan noch bei anderen.\n"
    "3️⃣ Geliehene Items werden pünktlich und vollständig zurückgegeben.\n"
    "4️⃣ Keine Werbung und kein Spam.\n"
    "5️⃣ Den Anweisungen von Leitung und Offizieren ist zu folgen.\n\n"
    "*Diese Regeln kannst du jederzeit direkt in dieser Nachricht ändern – /setup überschreibt sie nicht.*"
)
 
 
def build_overwrites(guild, roles, view, write, voice=False):
    view, write = set(view), set(write)
    keys = view | write | {"leader", "officer"}
    overwrites = {}
    for key in keys:
        target = guild.default_role if key == "everyone" else roles[key]
        can_write = key in write or key in ("leader", "officer")
        ow = discord.PermissionOverwrite(view_channel=True)
        if voice:
            ow.connect = can_write
            ow.speak = can_write
        else:
            ow.send_messages = can_write
            ow.send_messages_in_threads = can_write
        overwrites[target] = ow
    if "everyone" not in keys:
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
    extra = dict(connect=True, move_members=True) if voice else {}
    overwrites[guild.me] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, embed_links=True, manage_channels=True,
        manage_messages=True, read_message_history=True, **extra)
    return overwrites
 
 
async def ensure_role(guild, key, spec):
    name, colour, hoist, perms = spec
    permissions = discord.Permissions(**perms)
    wanted = dict(name=name, colour=discord.Colour(colour), hoist=hoist,
                  mentionable=(key == "lender"), permissions=permissions)
    role = find_role(guild, name, fuzzy=False)  # exakter Name hat Vorrang
    rid = await db.get_setting(guild.id, f"role_{key}")
    if role is None and rid:
        role = guild.get_role(int(rid))
    role = role or find_role(guild, name)
    created = role is None
    if created:
        role = await guild.create_role(**wanted, reason="ClanBot Setup")
    await db.set_setting(guild.id, f"role_{key}", role.id)
    return role, created
 
 
async def ensure_category(guild, spec, overwrites):
    cat = None
    cid = await db.get_setting(guild.id, f"cat_{spec['key']}")
    if cid:
        cat = guild.get_channel(int(cid))
    cat = cat or discord.utils.get(guild.categories, name=spec["name"])
    created = cat is None
    if created:
        cat = await guild.create_category(spec["name"], overwrites=overwrites, reason="ClanBot Setup")
    elif cat.overwrites != overwrites:
        await cat.edit(overwrites=overwrites, reason="ClanBot Setup")
    await db.set_setting(guild.id, f"cat_{spec['key']}", cat.id)
    return cat, created
 
 
async def ensure_channel(guild, spec, category, overwrites, voice):
    ch = None
    cid = await db.get_setting(guild.id, f"ch_{spec['key']}")
    if cid:
        ch = guild.get_channel(int(cid))
    if ch is None:
        wanted = spec["name"] if voice else spec["name"].lower()
        ch = discord.utils.find(lambda c: c.name == wanted and c.category_id == category.id, category.channels)
    created = ch is None
    if created:
        if voice:
            ch = await category.create_voice_channel(spec["name"], overwrites=overwrites, reason="ClanBot Setup")
        else:
            ch = await category.create_text_channel(spec["name"], topic=spec.get("topic"),
                                                    overwrites=overwrites, reason="ClanBot Setup")
    else:
        changes = {}
        if ch.overwrites != overwrites:
            changes["overwrites"] = overwrites
        if ch.category_id != category.id:
            changes["category"] = category
        if not voice and spec.get("topic") and ch.topic != spec["topic"]:
            changes["topic"] = spec["topic"]
        if changes:
            await ch.edit(reason="ClanBot Setup", **changes)
    await db.set_setting(guild.id, f"ch_{spec['key']}", ch.id)
    return ch, created
 
 
# Diese Rollen bleiben zusätzlich zu den Rollen aus config.py immer erhalten (Bots, VIP)
KEEP_EXTRA = ["⭐ | VIP", "🎶 | Musikbot", "🤖 | SquizyyBot"]
 
 
def unused_roles(guild):
    """Alle Rollen, die nicht zur Liste gehören (ohne @everyone, Bot-/Booster-Rollen und Rollen über dem Bot)."""
    keep = {_norm(spec[0]) for spec in ROLE_SPECS.values()} | {_norm(n) for n in KEEP_EXTRA}
    top = guild.me.top_role.position
    return [r for r in guild.roles
            if not r.is_default() and not r.managed and r.position < top and _norm(r.name) not in keep]
 
 
class CleanupView(discord.ui.View):
    def __init__(self, user_id, roles):
        super().__init__(timeout=300)
        self.user_id, self.roles = user_id, roles
 
    @discord.ui.button(label="Ja, alle löschen", emoji="🗑", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Nur der Admin, der /setup ausgeführt hat.", ephemeral=True)
        await interaction.response.defer()
        deleted = 0
        for role in self.roles:
            try:
                await role.delete(reason="ClanBot: nicht benötigte Rolle")
                deleted += 1
            except discord.HTTPException:
                pass
        self.stop()
        await interaction.edit_original_response(content=f"🗑 {deleted} von {len(self.roles)} Rollen gelöscht.", view=None)
 
    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Abgebrochen. Es wurde nichts gelöscht.", view=None)
 
 
class SetupCog(commands.Cog, name="Setup"):
    def __init__(self, bot):
        self.bot = bot
 
    @app_commands.command(name="setup", description="Richtet den Server ein bzw. bringt ihn auf den neuesten Stand")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        new_roles, new_cats, new_chans, checked = [], [], [], 0
        try:
            roles = {}
            for key in ROLE_ORDER:
                roles[key], created = await ensure_role(guild, key, ROLE_SPECS[key])
                if created:
                    new_roles.append(roles[key].name)
 
            top = guild.me.top_role.position
            if new_roles and top > len(ROLE_ORDER):
                try:
                    await guild.edit_role_positions(
                        positions={roles[k]: top - 1 - i for i, k in enumerate(ROLE_ORDER)
                                   if roles[k].name in new_roles})
                except discord.HTTPException:
                    pass
 
            channels = {}
            for cat_spec in LAYOUT:
                voice = cat_spec.get("voice", False)
                cat_ow = build_overwrites(guild, roles, cat_spec["view"], cat_spec["write"], voice)
                category, created = await ensure_category(guild, cat_spec, cat_ow)
                if created:
                    new_cats.append(category.name)
                for ch_spec in cat_spec["channels"]:
                    ow = build_overwrites(guild, roles, ch_spec.get("view", cat_spec["view"]),
                                          ch_spec.get("write", cat_spec["write"]), voice)
                    channels[ch_spec["key"]], created = await ensure_channel(guild, ch_spec, category, ow, voice)
                    checked += 1
                    if created:
                        new_chans.append(channels[ch_spec["key"]].name)
 
            await self.post_panels(guild, channels)
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Mir fehlen Rechte. Gib dem Bot **Administrator** (oder Rollen + Kanäle verwalten) und schiebe "
                "die Bot-Rolle in den Servereinstellungen ganz nach oben. Danach /setup erneut ausführen.")
 
        embed = discord.Embed(title="✅ Setup abgeschlossen", colour=discord.Colour.green())
        embed.add_field(name="Neue Rollen", value=", ".join(new_roles) or "–", inline=False)
        embed.add_field(name="Neue Kategorien", value=", ".join(new_cats) or "–", inline=False)
        embed.add_field(name="Neue Kanäle", value=", ".join(new_chans) or "–", inline=False)
        embed.add_field(name="Geprüft & aktualisiert",
                        value=f"{checked} Kanäle, Berechtigungen und Info-Nachrichten", inline=False)
        embed.add_field(name="Nächste Schritte",
                        value="• Items eintragen: `/item hinzufuegen`\n• Leitung/Offiziere/Verleiher Rollen geben\n"
                              "• Regeln im Regel-Kanal anpassen", inline=False)
        await interaction.followup.send(embed=embed)
 
        extras = unused_roles(guild)
        if extras:
            lines = "\n".join(f"• {r.name} ({len(r.members)} Personen)" for r in extras)[:1700]
            await interaction.followup.send(
                f"Diese Rollen gehören **nicht** zur Liste und würden gelöscht (nicht rückgängig zu machen):\n{lines}",
                view=CleanupView(interaction.user.id, extras), ephemeral=True)
 
    @app_commands.command(name="rollen", description="Zeigt, welche Rollen der Bot erkannt hat")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def roles_check(self, interaction: discord.Interaction):
        lines = []
        for key in ROLE_ORDER:
            role = await get_role(interaction.guild, key)
            found = f"{role.mention} ({len(role.members)} Personen)" if role else "❌ nicht gefunden"
            lines.append(f"**{ROLE_SPECS[key][0]}** → {found}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
 
    async def post_panels(self, guild, ch):
        blue = discord.Colour.blue()
        await ensure_message(guild, ch["rules"], "rules",
                             discord.Embed(title="📜 Clan-Regeln", description=RULES_TEXT, colour=discord.Colour.red()),
                             update=False)
        await ensure_message(guild, ch["welcome"], "welcome",
                             discord.Embed(title="Willkommen! ⛏️",
                                           description="Hier startest du. Lies die Regeln und bewirb dich im Ticket-Kanal.",
                                           colour=discord.Colour.green()), update=False)
        await ensure_message(guild, ch["roles"], "roles",
                             discord.Embed(title="🎭 Rollen",
                                           description="Möchtest du Items vom Clan leihen? Klick auf den Button, "
                                                       "dann schaltet sich das **Leihhaus** für dich frei.",
                                           colour=blue), BorrowerRoleView())
        await ensure_message(guild, ch["roles"], "skills",
                             discord.Embed(title="⚒️ Deine Spezialisierung",
                                           description="Was machst du im Clan am liebsten? Wähle **Farmer**, **Builder** "
                                                       "oder **Miner**. Ein Klick auf eine andere Rolle wechselt, "
                                                       "ein erneuter Klick gibt sie ab.", colour=discord.Colour.green()),
                             SkillRoleView())
        await ensure_message(guild, ch["tickets"], "tickets",
                             discord.Embed(title="🎫 Bewerbung & Support",
                                           description="Du willst in den Clan oder brauchst Hilfe? "
                                                       "Öffne ein privates Ticket.", colour=blue), TicketPanelView())
        await ensure_message(guild, ch["loan_info"], "loan_info",
                             discord.Embed(title="📘 So funktioniert das Leihhaus", colour=blue, description=(
                                 "1️⃣ Im **Katalog** siehst du, was verfügbar ist.\n"
                                 "2️⃣ Mit `/leihen anfragen` stellst du eine Anfrage (Item, Menge, Tage).\n"
                                 "3️⃣ Das Verleih-Team genehmigt oder lehnt ab – du bekommst eine DM.\n"
                                 "4️⃣ Gib das Item rechtzeitig zurück. Vorher erinnert dich der Bot.\n\n"
                                 "`/leihen meine` zeigt deine aktuellen Leihen.")))
        await refresh_catalog(guild)
 
 
async def setup(bot):
    await bot.add_cog(SetupCog(bot))
