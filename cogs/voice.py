import discord
from discord import app_commands
from discord.ext import commands

import db

NOT_OWNER = "Du musst dich in deinem eigenen Join-to-Create-Raum befinden."


def owner_overwrite():
    return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
                                       manage_channels=True, move_members=True)


async def lock_channel(channel, owner):
    overwrites = channel.overwrites
    for target, ow in overwrites.items():
        if isinstance(target, discord.Role):
            ow.connect = False
    overwrites.setdefault(channel.guild.default_role, discord.PermissionOverwrite()).connect = False
    overwrites[owner] = owner_overwrite()
    await channel.edit(overwrites=overwrites)


async def unlock_channel(channel, owner):
    overwrites = dict(channel.category.overwrites) if channel.category else {}
    overwrites[owner] = owner_overwrite()
    await channel.edit(overwrites=overwrites)


def is_locked(channel):
    return channel.overwrites_for(channel.guild.default_role).connect is False


async def owned_channel(interaction: discord.Interaction):
    """Für Slash-Commands: der Raum, in dem der Nutzer gerade sitzt und den er besitzt."""
    state = interaction.user.voice
    if not state or not state.channel:
        return None
    row = await db.fetchone("SELECT * FROM temp_voice WHERE channel_id=? AND owner_id=?",
                            (state.channel.id, interaction.user.id))
    return state.channel if row else None


async def check_owner(interaction: discord.Interaction):
    """Für das Panel: nur der Besitzer des Raums, in dessen Chat geklickt wird, darf steuern."""
    row = await db.fetchone("SELECT * FROM temp_voice WHERE channel_id=? AND owner_id=?",
                            (interaction.channel_id, interaction.user.id))
    if not row:
        await interaction.response.send_message("Nur der Besitzer dieses Raums darf das.", ephemeral=True)
        return None
    return interaction.channel


# ---------------------------------------------------------------- Panel

def panel_embed():
    embed = discord.Embed(
        title="🎛️ Raum-Steuerung",
        description="Das ist dein eigener Raum! Mit den Buttons steuerst du ihn.\n"
                    "Nur der Besitzer kann sie benutzen. Ist der Raum leer, wird er automatisch gelöscht.",
        colour=discord.Colour.blurple())
    embed.add_field(name="✏️ Umbenennen / 👥 Limit", value="Name und maximale Personenzahl ändern", inline=False)
    embed.add_field(name="🔒 Sperren / Freigeben", value="Raum für alle schließen oder wieder öffnen", inline=False)
    embed.add_field(name="➕ Einladen / 👢 Rauswerfen / 👑 Übertragen",
                    value="Einzelne Personen zulassen, entfernen oder den Raum übergeben", inline=False)
    return embed


class RenameModal(discord.ui.Modal, title="Raum umbenennen"):
    name = discord.ui.TextInput(label="Neuer Name", max_length=90, placeholder="z. B. Mining-Crew")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.edit(name=self.name.value)
        await interaction.followup.send(f"✏️ Der Raum heißt jetzt **{self.name.value}**.", ephemeral=True)


class LimitModal(discord.ui.Modal, title="Nutzerlimit setzen"):
    limit = discord.ui.TextInput(label="Limit (0 = unbegrenzt, max. 99)", max_length=2, placeholder="z. B. 5")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            number = int(self.limit.value)
        except ValueError:
            number = -1
        if not 0 <= number <= 99:
            return await interaction.response.send_message("Bitte eine Zahl von 0 bis 99 eingeben.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.edit(user_limit=number)
        await interaction.followup.send(f"👥 Limit: {number or 'unbegrenzt'}.", ephemeral=True)


class UserPick(discord.ui.View):
    def __init__(self, action: str, channel: discord.VoiceChannel, owner: discord.Member):
        super().__init__(timeout=60)
        self.action, self.channel, self.owner = action, channel, owner

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Person auswählen …", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target = select.values[0]
        channel = self.channel
        if not isinstance(target, discord.Member) or target.bot:
            text = "Bitte wähle ein Servermitglied (keinen Bot)."
        elif self.action == "invite":
            await channel.set_permissions(target, view_channel=True, connect=True, speak=True)
            text = f"✅ {target.mention} darf jetzt in den Raum."
        elif target.id == self.owner.id:
            text = "Das bist du selbst. 😉"
        elif self.action == "kick":
            await channel.set_permissions(target, connect=False)
            if target.voice and target.voice.channel == channel:
                await target.move_to(None)
            text = f"👢 {target.mention} wurde rausgeworfen und kann nicht mehr beitreten, bis du die Person wieder einlädst."
        else:  # transfer
            await db.execute("UPDATE temp_voice SET owner_id=? WHERE channel_id=?", (target.id, channel.id))
            await channel.set_permissions(self.owner, overwrite=None)
            await channel.set_permissions(target, overwrite=owner_overwrite())
            await channel.send(f"👑 {target.mention} ist jetzt Besitzer dieses Raums.")
            text = f"👑 {target.mention} ist jetzt Besitzer."
        await interaction.response.edit_message(content=text, view=None)


class VoiceControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Umbenennen", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="vc:rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_owner(interaction):
            await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="vc:limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_owner(interaction):
            await interaction.response.send_modal(LimitModal())

    @discord.ui.button(label="Sperren / Freigeben", emoji="🔒", style=discord.ButtonStyle.primary, custom_id="vc:lock", row=0)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await check_owner(interaction)
        if not channel:
            return
        await interaction.response.defer(ephemeral=True)
        if is_locked(channel):
            await unlock_channel(channel, interaction.user)
            await interaction.followup.send("🔓 Raum ist wieder offen.", ephemeral=True)
        else:
            await lock_channel(channel, interaction.user)
            await interaction.followup.send("🔒 Raum gesperrt. Mit **Einladen** lässt du einzelne Leute rein.", ephemeral=True)

    @discord.ui.button(label="Einladen", emoji="➕", style=discord.ButtonStyle.success, custom_id="vc:invite", row=1)
    async def invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await check_owner(interaction)
        if channel:
            await interaction.response.send_message("Wen möchtest du einladen?", ephemeral=True,
                                                    view=UserPick("invite", channel, interaction.user))

    @discord.ui.button(label="Rauswerfen", emoji="👢", style=discord.ButtonStyle.danger, custom_id="vc:kick", row=1)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await check_owner(interaction)
        if channel:
            await interaction.response.send_message("Wen möchtest du rauswerfen?", ephemeral=True,
                                                    view=UserPick("kick", channel, interaction.user))

    @discord.ui.button(label="Übertragen", emoji="👑", style=discord.ButtonStyle.secondary, custom_id="vc:transfer", row=1)
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await check_owner(interaction)
        if channel:
            await interaction.response.send_message("Wem möchtest du den Raum übergeben?", ephemeral=True,
                                                    view=UserPick("transfer", channel, interaction.user))


# ---------------------------------------------------------------- Cog

class Voice(commands.Cog):
    voice = app_commands.Group(name="voice", description="Verwalte deinen privaten Voice-Raum", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VoiceControlView())

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
            channel = None
            try:
                channel = await guild.create_voice_channel(
                    f"🎮 {member.display_name}"[:100], category=category, overwrites=overwrites,
                    reason="Join to Create")
                await db.execute("INSERT INTO temp_voice (channel_id, guild_id, owner_id) VALUES (?,?,?)",
                                 (channel.id, guild.id, member.id))
                await member.move_to(channel)
            except discord.HTTPException:
                # z. B. Person hat den Kanal schon wieder verlassen -> Raum nicht liegen lassen
                if channel:
                    try:
                        await channel.delete(reason="Join to Create fehlgeschlagen")
                    except discord.HTTPException:
                        pass
                    await db.execute("DELETE FROM temp_voice WHERE channel_id=?", (channel.id,))
                return
            # Steuer-Panel automatisch im Chat des neuen Raums posten
            try:
                await channel.send(content=member.mention, embed=panel_embed(), view=VoiceControlView())
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
        await lock_channel(ch, interaction.user)
        await interaction.response.send_message("🔒 Raum gesperrt. Mit /voice erlauben lädst du Leute ein.", ephemeral=True)

    @voice.command(name="freigeben", description="Raum wieder für alle Berechtigten öffnen")
    async def unlock(self, interaction: discord.Interaction):
        ch = await owned_channel(interaction)
        if not ch:
            return await interaction.response.send_message(NOT_OWNER, ephemeral=True)
        await unlock_channel(ch, interaction.user)
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
