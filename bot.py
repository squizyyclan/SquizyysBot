import os
import traceback
 
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
 
import db
 
load_dotenv()
 
# Der Bot läuft nur auf EINEM Server. Server-ID: Discord -> Entwicklermodus -> Rechtsklick auf Server -> ID kopieren
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
 
intents = discord.Intents.default()
intents.members = True  # im Developer Portal aktivieren: "Server Members Intent"
 
 
class GuildOnlyTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id == GUILD_ID
 
 
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, tree_cls=GuildOnlyTree)
 
    async def setup_hook(self):
        await db.init()
        for ext in ("cogs.setup", "cogs.loans", "cogs.voice", "cogs.community"):
            await self.load_extension(ext)
        try:  # Die Website ist optional: bei einem Fehler läuft der Bot trotzdem weiter
            await self.load_extension("cogs.website")
        except Exception:
            traceback.print_exc()
            print("Website konnte nicht gestartet werden - der Bot läuft ohne sie weiter.")
        # Commands nur für den eigenen Server registrieren (sofort verfügbar), globale entfernen
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
 
    async def on_ready(self):
        print(f"Eingeloggt als {self.user}")
        for guild in self.guilds:
            if guild.id != GUILD_ID:
                print(f"Verlasse fremden Server: {guild.name}")
                await guild.leave()
 
    async def on_guild_join(self, guild: discord.Guild):
        if guild.id != GUILD_ID:
            await guild.leave()
 
 
bot = ClanBot()
 
 
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        text = "Dafür fehlen dir die nötigen Rechte."
    elif isinstance(error, app_commands.CheckFailure):
        text = str(error) or "Das darfst du nicht."
    else:
        text = "Da ist etwas schiefgelaufen. 😕"
        traceback.print_exception(error)
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
 
 
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token or not GUILD_ID:
        raise SystemExit("DISCORD_TOKEN und GUILD_ID müssen gesetzt sein (siehe .env.example)")
    bot.run(token)
