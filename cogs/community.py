import asyncio
import datetime as dt
import io
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import SKILL_ROLES_EXCLUSIVE
from utils import get_ch, get_role, is_staff, modlog, staff_only


# ---------------------------------------------------------------- Tickets

TICKET_INTRO = {
    "bewerbung": ("📝 Bewerbung",
                  "Erzähl uns kurz:\n• Dein Minecraft-Name\n• Wie lange spielst du schon?\n"
                  "• Was kannst du gut (Bauen, PvP, Farmen …)?\n• Warum möchtest du zu uns?"),
    "support": ("🆘 Support", "Beschreibe dein Anliegen so genau wie möglich. Das Team meldet sich bald."),
}


async def open_ticket(interaction: discord.Interaction, kind: str):
    guild, user = interaction.guild, interaction.user
    cat = guild.get_channel(int(await db.get_setting(guild.id, "cat_tickets") or 0))
    if not cat:
        return await interaction.response.send_message("Ticket-System ist noch nicht eingerichtet (/setup).", ephemeral=True)
    tag = f"ticket:{user.id}"
    for ch in cat.text_channels:
        if ch.topic and ch.topic.startswith(tag):
            return await interaction.response.send_message(f"Du hast schon ein Ticket: {ch.mention}", ephemeral=True)

    po = discord.PermissionOverwrite
    overwrites = {
        guild.default_role: po(view_channel=False),
        user: po(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        guild.me: po(view_channel=True, send_messages=True, manage_channels=True),
    }
    for key in ("leader", "officer"):
        role = await get_role(guild, key)
        if role:
            overwrites[role] = po(view_channel=True, send_messages=True, read_message_history=True)
    channel = await cat.create_text_channel(f"{kind}-{user.name}"[:90], topic=f"{tag}:{kind}", overwrites=overwrites)

    title, text = TICKET_INTRO[kind]
    await channel.send(content=user.mention, embed=discord.Embed(title=title, description=text, colour=discord.Colour.blurple()),
                       view=TicketCloseView())
    await interaction.response.send_message(f"Dein Ticket: {channel.mention}", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Beim Clan bewerben", emoji="📝", style=discord.ButtonStyle.success,
                       custom_id="clan:ticket:bewerbung")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "bewerbung")

    @discord.ui.button(label="Support", emoji="🆘", style=discord.ButtonStyle.secondary,
                       custom_id="clan:ticket:support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_ticket(interaction, "support")


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", emoji="🔒", style=discord.ButtonStyle.danger,
                       custom_id="clan:ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel, guild = interaction.channel, interaction.guild
        topic = channel.topic or ""
        owner_id = int(topic.split(":")[1]) if topic.startswith("ticket:") else None
        if interaction.user.id != owner_id and not await is_staff(interaction.user, extra=()):
            return await interaction.response.send_message("Nur Ersteller oder Team dürfen schließen.", ephemeral=True)
        await interaction.response.send_message("🔒 Ticket wird in 5 Sekunden geschlossen …")

        lines = [f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {m.content}"
                 async for m in channel.history(limit=500, oldest_first=True)]
        log = await get_ch(guild, "modlog")
        if log:
            data = io.BytesIO("\n".join(lines).encode("utf-8"))
            await log.send(f"📁 Transcript von **{channel.name}**", file=discord.File(data, filename=f"{channel.name}.txt"))
        await asyncio.sleep(5)
        await channel.delete(reason="Ticket geschlossen")


# ---------------------------------------------------------------- Spezialisierungs-Rollen

SKILL_ROLES = {"farmer": ("Farmer", "🌾"), "builder": ("Builder", "🏗️"), "miner": ("Miner", "⛏️")}


class SkillRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, (label, emoji) in SKILL_ROLES.items():
            button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary,
                                       custom_id=f"clan:skill:{key}")
            button.callback = self.make_callback(key)
            self.add_item(button)

    def make_callback(self, key):
        async def callback(interaction: discord.Interaction):
            guild, member = interaction.guild, interaction.user
            role = await get_role(guild, key)
            if not role:
                return await interaction.response.send_message(
                    "Die Rolle fehlt noch – ein Admin muss /setup ausführen.", ephemeral=True)
            if role in member.roles:
                await member.remove_roles(role)
                return await interaction.response.send_message(f"Du bist kein {role.name} mehr.", ephemeral=True)
            if SKILL_ROLES_EXCLUSIVE:
                for other_key in SKILL_ROLES:
                    other = await get_role(guild, other_key)
                    if other_key != key and other and other in member.roles:
                        await member.remove_roles(other)
            await member.add_roles(role)
            await interaction.response.send_message(f"Du bist jetzt **{role.name}**! {SKILL_ROLES[key][1]}", ephemeral=True)
        return callback


# ---------------------------------------------------------------- Cog

def can_act(actor: discord.Member, target: discord.Member):
    return (target != actor and target != actor.guild.owner and not target.bot
            and (actor == actor.guild.owner or target.top_role < actor.top_role))


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketCloseView())
        self.bot.add_view(SkillRoleView())

    # ----- Willkommen & Auto-Rolle

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        role = await get_role(member.guild, "recruit")
        if role:
            try:
                await member.add_roles(role, reason="Auto-Rolle")
            except discord.HTTPException:
                pass
        ch = await get_ch(member.guild, "welcome")
        if ch:
            embed = discord.Embed(
                title="Willkommen im Clan! ⛏️",
                description=f"Schön, dass du da bist, {member.mention}!\n"
                            "Lies die Regeln, bewirb dich im Ticket-Kanal und hol dir bei Bedarf die Leiher-Rolle.",
                colour=discord.Colour.green())
            embed.set_thumbnail(url=member.display_avatar.url)
            await ch.send(content=member.mention, embed=embed)

    # ----- Ankündigungen

    @app_commands.command(name="ankuendigung", description="Ankündigung im News-Kanal posten")
    @app_commands.guild_only()
    @staff_only(extra=())
    async def announce(self, interaction: discord.Interaction, titel: str, text: str, alle_pingen: bool = False):
        ch = await get_ch(interaction.guild, "news")
        if not ch:
            return await interaction.response.send_message("News-Kanal fehlt – bitte /setup ausführen.", ephemeral=True)
        embed = discord.Embed(title=titel, description=text.replace("\\n", "\n"), colour=discord.Colour.gold())
        embed.set_footer(text=f"von {interaction.user.display_name}")
        await ch.send(content="@everyone" if alle_pingen else None, embed=embed,
                      allowed_mentions=discord.AllowedMentions(everyone=alle_pingen))
        await interaction.response.send_message(f"Gepostet in {ch.mention}.", ephemeral=True)

    # ----- Moderation

    @app_commands.command(name="clear", description="Nachrichten löschen")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=anzahl)
        await interaction.followup.send(f"🧹 {len(deleted)} Nachrichten gelöscht.", ephemeral=True)

    @app_commands.command(name="timeout", description="Person stummschalten (Timeout)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, person: discord.Member,
                      minuten: app_commands.Range[int, 1, 40320], grund: Optional[str] = None):
        if not can_act(interaction.user, person):
            return await interaction.response.send_message("Das darfst du bei dieser Person nicht.", ephemeral=True)
        await person.timeout(dt.timedelta(minutes=minuten), reason=grund)
        await modlog(interaction.guild, f"⏳ {person.mention} {minuten} Min. Timeout von {interaction.user.mention}: {grund or '–'}")
        await interaction.response.send_message(f"{person.mention} ist für {minuten} Min. stumm.", ephemeral=True)

    @app_commands.command(name="kick", description="Person kicken")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, person: discord.Member, grund: Optional[str] = None):
        if not can_act(interaction.user, person):
            return await interaction.response.send_message("Das darfst du bei dieser Person nicht.", ephemeral=True)
        await person.kick(reason=grund)
        await modlog(interaction.guild, f"👢 {person} gekickt von {interaction.user.mention}: {grund or '–'}")
        await interaction.response.send_message(f"{person} wurde gekickt.", ephemeral=True)

    @app_commands.command(name="ban", description="Person bannen")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, person: discord.Member, grund: Optional[str] = None):
        if not can_act(interaction.user, person):
            return await interaction.response.send_message("Das darfst du bei dieser Person nicht.", ephemeral=True)
        await person.ban(reason=grund)
        await modlog(interaction.guild, f"🔨 {person} gebannt von {interaction.user.mention}: {grund or '–'}")
        await interaction.response.send_message(f"{person} wurde gebannt.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Community(bot))
