import re
from typing import Optional
 
import discord
from discord import app_commands
from discord.ext import commands
 
import db
from utils import staff_only
 
NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
 
 
def valid_ign(name):
    return bool(NAME_RE.match(name or ""))
 
 
async def get_ign(discord_id):
    row = await db.fetchone("SELECT mc_name FROM players WHERE discord_id=?", (int(discord_id),))
    return row["mc_name"] if row else None
 
 
async def set_ign(discord_id, name):
    await db.execute("INSERT INTO players (discord_id, mc_name) VALUES (?,?) "
                     "ON CONFLICT(discord_id) DO UPDATE SET mc_name=excluded.mc_name", (int(discord_id), name))
 
 
class Ingame(commands.Cog):
    ign = app_commands.Group(name="ign", description="Dein Ingame-Name", guild_only=True)
 
    def __init__(self, bot):
        self.bot = bot
 
    async def cog_load(self):
        await db.execute("CREATE TABLE IF NOT EXISTS players (discord_id INTEGER PRIMARY KEY, mc_name TEXT)")
 
    @ign.command(name="setzen", description="Hinterlege deinen Minecraft-Namen")
    async def set_own(self, interaction: discord.Interaction, name: str):
        if not valid_ign(name):
            return await interaction.response.send_message(
                "Ungültiger Name (3–16 Zeichen: Buchstaben, Zahlen, _).", ephemeral=True)
        await set_ign(interaction.user.id, name)
        await interaction.response.send_message(f"✅ Dein Ingame-Name ist jetzt **{name}**.", ephemeral=True)
 
    @ign.command(name="anzeigen", description="Ingame-Namen anzeigen")
    async def show(self, interaction: discord.Interaction, person: Optional[discord.Member] = None):
        person = person or interaction.user
        name = await get_ign(person.id)
        await interaction.response.send_message(
            f"{person.mention}: **{name}**" if name else f"{person.mention} hat noch keinen Ingame-Namen.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
 
    @ign.command(name="fuer", description="Ingame-Namen für eine Person setzen (Team)")
    @staff_only(extra=())
    async def set_for(self, interaction: discord.Interaction, person: discord.Member, name: str):
        if not valid_ign(name):
            return await interaction.response.send_message("Ungültiger Name.", ephemeral=True)
        await set_ign(person.id, name)
        await interaction.response.send_message(f"✅ {person.mention} = **{name}**", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
 
 
async def setup(bot):
    await bot.add_cog(Ingame(bot))
