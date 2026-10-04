import discord
from discord import app_commands
 
import db
from config import ROLE_SPECS
 
 
def _key(name):
    """Vergleichsschlüssel: ohne Emoji-Zusatz, nur Text hinter '|', klein geschrieben."""
    return " ".join(name.replace("\ufe0f", "").split("|")[-1].split()).casefold()
 
 
def find_role(guild, name):
    """Findet eine vorhandene Rolle, auch bei kleinen Abweichungen (Leerzeichen, Emoji-Präfix)."""
    for role in guild.roles:
        if not role.is_default() and not role.managed and _key(role.name) == _key(name):
            return role
    return None
 
 
async def get_ch(guild, key):
    cid = await db.get_setting(guild.id, f"ch_{key}")
    return guild.get_channel(int(cid)) if cid else None
 
 
async def get_role(guild, key):
    rid = await db.get_setting(guild.id, f"role_{key}")
    role = guild.get_role(int(rid)) if rid else None
    if role is None and key in ROLE_SPECS:  # Fallback: Rolle über ihren Namen finden
        role = find_role(guild, ROLE_SPECS[key][0])
    return role
 
 
async def is_staff(member, extra=("lender",)):
    """Admin, Clan-Leitung, Offizier (und standardmäßig Verleiher)."""
    if member.guild_permissions.administrator:
        return True
    for key in ("leader", "officer", *extra):
        role = await get_role(member.guild, key)
        if role and role in member.roles:
            return True
    return False
 
 
def staff_only(extra=("lender",)):
    async def predicate(interaction: discord.Interaction):
        if await is_staff(interaction.user, extra):
            return True
        raise app_commands.CheckFailure("Das dürfen nur Teammitglieder (Leitung, Offiziere, Verleiher).")
    return app_commands.check(predicate)
 
 
async def ensure_message(guild, channel, key, embed, view=None, update=True):
    """Sendet eine Nachricht einmalig und aktualisiert sie später (statt neu zu posten)."""
    mid = await db.get_setting(guild.id, f"msg_{key}")
    if mid:
        try:
            msg = await channel.fetch_message(int(mid))
            if update:
                await msg.edit(embed=embed, view=view)
            return msg
        except (discord.NotFound, discord.Forbidden):
            pass
    msg = await channel.send(embed=embed, view=view)
    await db.set_setting(guild.id, f"msg_{key}", msg.id)
    return msg
 
 
async def modlog(guild, text):
    ch = await get_ch(guild, "modlog")
    if ch:
        await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
 
