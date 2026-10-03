import discord
from discord import app_commands
from discord.ext import commands

import db

NOT_OWNER = "Du musst dich in deinem eigenen Join-to-Create-Raum befinden."


async def owned_channel(interaction: discord.Interaction):
    state = interaction.user.voice
    if not state or not state.channel:
        return None
    row = await db.fetchone("SELECT * FROM temp_voice WHERE channel_id=? AND owner_id=?",
                            (state.channel.id, interaction.user.id))
    return state.channel if row else None


def owner_overwrite():
    return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
                                       manage_channels=True, move_members=True)


class Voice(commands.Cog):
    voice = app_commands.Group(name="voice", description="Verwalte deinen privaten Voice-Raum", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Nach Neustart: leere oder verschwundene Temp-Kanäle aufräumen
        for row in await db.fetchall("SELECT * FROM temp_voice"):
            ch = self.bot.get_channel(row["channel_id"])
            if ch is None:
                await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (row["channel_id"],))
            elif not ch.members:
                try:
                    await ch.delete(reason="Leerer Join-to-Create-Raum")
                except discord.HTTPException:
                    pass
                await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (row["channel_id"],))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        jtc = await db.get_setting(guild.id, "ch_jtc")

        # Beitritt zum "Raum erstellen"-Kanal -> eigenen Raum anlegen
        if jtc and after.channel and after.channel.id == int(jtc):
            category = after.channel.category
            overwrites = dict(category.overwrites) if category else {}
            overwrites[member] = owner_overwrite()
            try:
                channel = await guild.create_voice_channel(
                    f"🎮 {member.display_name}"[:100], category=category, overwrites=overwrites,
                    reason="Join to Create")
                await db.execute("INSERT INTO temp_voice (channel_id, guild_id, owner_id) VALUES (?,?,?)",
                                 (channel.id, guild.id, member.id))
                await member.move_to(channel)
            except discord.HTTPException:
                pass

        # Verlassen eines Temp-Raums -> löschen, wenn leer
        if before.channel and before.channel != after.channel:
            row = await db.fetchone("SELECT 1 FROM temp_voice WHERE channel_id=?", (before.channel.id,))
            if row and not before.channel.members:
                try:
                    await before.channel.delete(reason="Join to Create: Raum leer")
                except discord.HTTPException:
                    pass
                await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (before.channel.id,))

    @voice.command(name="name", description="Benenne deinen Raum um")
    async def rename(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 90]):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        await ch.edit(name=name)
        await interaction.response.send_message(f"Raum heißt jetzt **{name}**.", ephemeral=True)

    @voice.command(name="limit", description="Setze ein Nutzerlimit (0 = unbegrenzt)")
    async def limit(self, interaction: discord.Interaction, anzahl: app_commands.Range[int, 0, 99]):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        await ch.edit(user_limit=anzahl)
        await interaction.response.send_message(f"Limit: {anzahl or 'unbegrenzt'}.", ephemeral=True)

    @voice.command(name="sperren", description="Niemand außer dir (und Erlaubten) kann beitreten")
    async def lock(self, interaction: discord.Interaction):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        overwrites = ch.overwrites
        for target, ow in overwrites.items():
            if isinstance(target, discord.Role):
                ow.connect = False
        overwrites.setdefault(interaction.guild.default_role, discord.PermissionOverwrite()).connect = False
        overwrites[interaction.user] = owner_overwrite()
        await ch.edit(overwrites=overwrites)
        await interaction.response.send_message("🔒 Raum gesperrt. Mit /voice erlauben lädst du Leute ein.", ephemeral=True)

    @voice.command(name="freigeben", description="Raum wieder für alle Berechtigten öffnen")
    async def unlock(self, interaction: discord.Interaction):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        overwrites = dict(ch.category.overwrites) if ch.category else {}
        overwrites[interaction.user] = owner_overwrite()
        await ch.edit(overwrites=overwrites)
        await interaction.response.send_message("🔓 Raum ist wieder offen.", ephemeral=True)

    @voice.command(name="erlauben", description="Erlaube einer Person den Beitritt")
    async def allow(self, interaction: discord.Interaction, person: discord.Member):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        await ch.set_permissions(person, view_channel=True, connect=True, speak=True)
        await interaction.response.send_message(f"{person.mention} darf jetzt rein.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Voice(bot))
