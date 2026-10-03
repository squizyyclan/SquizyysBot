import discord
from discord import app_commands
from discord.ext import commands

import db
from cogs.community import TicketPanelView
from cogs.loans import BorrowerRoleView, refresh_catalog
from config import LAYOUT, ROLE_ORDER, ROLE_SPECS
from utils import ensure_message

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
    role = None
    rid = await db.get_setting(guild.id, f"role_{key}")
    if rid:
        role = guild.get_role(int(rid))
    role = role or discord.utils.get(guild.roles, name=name)
    created = role is None
    if created:
        role = await guild.create_role(**wanted, reason="ClanBot Setup")
    elif (role.name != name or role.colour.value != colour or role.hoist != hoist
          or role.permissions != permissions or role.mentionable != wanted["mentionable"]):
        try:
            await role.edit(**wanted, reason="ClanBot Setup")
        except discord.Forbidden:
            pass
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
            if top > len(ROLE_ORDER):
                try:
                    await guild.edit_role_positions(
                        positions={roles[k]: top - 1 - i for i, k in enumerate(ROLE_ORDER)})
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
