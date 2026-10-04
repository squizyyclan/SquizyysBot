import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from urllib.parse import urlencode
 
import discord
from aiohttp import ClientSession, web
from discord.ext import commands
 
import db
from cogs.loans import available, loan_embed, loan_view, refresh_catalog
from cogs.loans import now as loan_now
from config import MAX_OPEN_LOANS, ROLE_SPECS
from utils import ensure_message, get_ch, get_role, is_staff
 
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CLAN = html.escape(os.getenv("CLAN_NAME", "Squizyys"))
ROLES = ("Farmer", "Builder", "Miner", "Egal")
COLORS = {"pending": 0xF1C40F, "accepted": 0x2ECC71, "declined": 0xE74C3C}
hits = {}
 
TAG = html.escape(os.getenv("CLAN_TAG", ""))
TEXT = html.escape(os.getenv("CLAN_TEXT", "Zusammen spielen, zusammen wachsen. Ein Minecraft-Clan mit Leuten, die zusammenhalten."))
YEAR = html.escape(os.getenv("CLAN_FOUNDED", "2026"))
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
SECRET = (os.getenv("SESSION_SECRET") or os.getenv("DISCORD_TOKEN", "x")).encode()
 
 
async def leader_of(member):
    if member.guild_permissions.administrator:
        return True
    role = await get_role(member.guild, "leader")
    return bool(role and role in member.roles)
 
 
def sign(data):
    body = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return body + "." + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
 
 
def unsign(value):
    try:
        body, sig = value.rsplit(".", 1)
        if hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
            return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        pass
    return None
 
 
def fail(text, status=400):
    return web.json_response({"message": text}, status=status)
 
 
def app_embed(r, footer=None):
    e = discord.Embed(title=f"📝 Bewerbung #{r['id']}", colour=COLORS[r["status"]])
    e.add_field(name="Minecraft", value=r["minecraft"])
    e.add_field(name="Discord", value=r["discord_name"])
    e.add_field(name="Wunschrolle", value=r["role"])
    e.add_field(name="Erfahrung", value=r["experience"] or "–", inline=False)
    e.add_field(name="Motivation", value=r["motivation"], inline=False)
    if footer:
        e.set_footer(text=footer)
    return e
 
 
class AppButton(discord.ui.DynamicItem[discord.ui.Button], template=r"app:(?P<action>accept|decline):(?P<id>\d+)"):
    def __init__(self, action, app_id):
        ok = action == "accept"
        super().__init__(discord.ui.Button(
            label="Annehmen" if ok else "Ablehnen", emoji="✅" if ok else "❌",
            style=discord.ButtonStyle.success if ok else discord.ButtonStyle.danger,
            custom_id=f"app:{action}:{app_id}"))
        self.action, self.app_id = action, app_id
 
    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["id"]))
 
    async def callback(self, interaction: discord.Interaction):
        if not await is_staff(interaction.user, extra=()):
            return await interaction.response.send_message("Nur Leitung und Offiziere.", ephemeral=True)
        row = await db.fetchone("SELECT * FROM applications WHERE id=?", (self.app_id,))
        if not row or row["status"] != "pending":
            return await interaction.response.send_message("Schon bearbeitet.", ephemeral=True)
        accepted = self.action == "accept"
        await db.execute("UPDATE applications SET status=? WHERE id=?",
                         ("accepted" if accepted else "declined", self.app_id))
        row = await db.fetchone("SELECT * FROM applications WHERE id=?", (self.app_id,))
        guild = interaction.guild
        member = guild.get_member_named(row["discord_name"])
        note = "Person nicht auf dem Server gefunden – bitte selbst melden."
        if member:
            if accepted:
                full, recruit = await get_role(guild, "member"), await get_role(guild, "recruit")
                if full:
                    await member.add_roles(full)
                if recruit and recruit in member.roles:
                    await member.remove_roles(recruit)
            try:
                await member.send("🎉 Deine Bewerbung wurde angenommen! Willkommen im Clan." if accepted
                                  else "Deine Bewerbung wurde leider abgelehnt.")
            except discord.HTTPException:
                pass
            note = f"{member.mention} wurde informiert" + (" und ist jetzt Mitglied." if accepted else ".")
        await interaction.response.edit_message(
            embed=app_embed(row, f"{'Angenommen' if accepted else 'Abgelehnt'} von {interaction.user.display_name}"),
            view=None)
        await interaction.followup.send(note, ephemeral=True)
 
 
class Website(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.runner = None
 
    async def cog_load(self):
        await db.execute(
            "CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, "
            "minecraft TEXT, discord_name TEXT, role TEXT, experience TEXT, motivation TEXT, status TEXT, "
            "created_at TEXT, message_id INTEGER)")
        self.bot.add_dynamic_items(AppButton)
        app = web.Application(client_max_size=20_000)
        app.add_routes([web.get("/", self.index), web.get("/api/items", self.items),
                        web.post("/api/bewerbung", self.apply), web.get("/api/me", self.me),
                        web.get("/login", self.login), web.get("/callback", self.callback),
                        web.get("/logout", self.logout), web.get("/api/members", self.members),
                        web.get("/api/rules", self.rules), web.get("/api/stats", self.stats),
                        web.post("/api/leihen", self.borrow), web.get("/logo.jpg", self.logo),
                        web.get("/app.js", self.script), web.post("/api/regeln", self.save_rules),
                        web.post("/api/item", self.edit_item),
                        web.get("/api/konto", self.konto), web.post("/api/konto", self.save_konto)])
        try:
            self.runner = web.AppRunner(app)
            await self.runner.setup()
            await web.TCPSite(self.runner, "0.0.0.0", int(os.getenv("PORT", "8080"))).start()
            print("Website läuft")
        except Exception as error:  # Bot soll auch ohne Website weiterlaufen
            print(f"Website konnte nicht gestartet werden: {error}")
 
    async def cog_unload(self):
        if self.runner:
            await self.runner.cleanup()
 
    async def logo(self, request):
        return web.FileResponse(os.path.join(os.path.dirname(__file__), "logo.jpg"))
 
    async def index(self, request):
        with open(os.path.join(os.path.dirname(__file__), "page.html"), encoding="utf-8") as f:
            page = f.read()
        for key, value in (("__NAME__", CLAN), ("__TAG__", TAG), ("__TEXT__", TEXT), ("__YEAR__", YEAR)):
            page = page.replace(key, value)
        return web.Response(text=page, content_type="text/html")
 
    async def items(self, request):
        rows = await db.fetchall("SELECT * FROM items WHERE guild_id=? ORDER BY name", (GUILD_ID,))
        return web.json_response([
            {"name": r["name"], "stock": r["stock"], "available": await available(r["id"]),
             "description": r["description"] or ""} for r in rows])
 
    def user(self, request):
        return unsign(request.cookies.get("s", ""))
 
    async def script(self, request):
        return web.FileResponse(os.path.join(os.path.dirname(__file__), "app.js"))
 
    async def member_of(self, request):
        user, guild = self.user(request), self.bot.get_guild(GUILD_ID)
        return guild, (guild.get_member(int(user["id"])) if user and guild else None)
 
    async def me(self, request):
        guild, member = await self.member_of(request)
        return web.json_response({
            "user": self.user(request), "login": bool(CLIENT_ID and CLIENT_SECRET and PUBLIC_URL),
            "leader": bool(member and await leader_of(member)), "staff": bool(member and await is_staff(member))})
 
    async def save_rules(self, request):
        guild, member = await self.member_of(request)
        if not member or not await leader_of(member):
            return fail("Nur die Clan-Leitung darf die Regeln ändern.", 403)
        try:
            lines = [x.strip() for x in str((await request.json())["rules"]).split("\n") if x.strip()][:20]
        except Exception:
            return fail("Ungültige Anfrage.")
        text = "\n".join((f"{n}\ufe0f\u20e3 " if n < 10 else "🔹 ") + x[:200] for n, x in enumerate(lines, 1))
        channel = await get_ch(guild, "rules")
        if not channel:
            return fail("Der Regel-Kanal fehlt (/setup).", 503)
        await ensure_message(guild, channel, "rules", discord.Embed(
            title="📜 Clan-Regeln", description=text or "–", colour=discord.Colour.red()))
        return web.json_response({"message": "✅ Regeln gespeichert."})
 
    async def konto(self, request):
        raw = await db.get_setting(GUILD_ID, "konto")
        return web.json_response(json.loads(raw) if raw else {})
 
    async def save_konto(self, request):
        guild, member = await self.member_of(request)
        if not member or not await leader_of(member):
            return fail("Nur die Clan-Leitung darf das Konto ändern.", 403)
        try:
            d = await request.json()
            values = {k: int(d[k]) for k in ("balance", "day", "week", "month")}
        except Exception:
            return fail("Bitte alle vier Zahlen ausfüllen.")
        if any(abs(v) > 10**15 for v in values.values()):
            return fail("Eine Zahl ist zu groß.")
        values.update(updated=dt.datetime.now(dt.timezone.utc).isoformat(), by=member.display_name)
        await db.set_setting(GUILD_ID, "konto", json.dumps(values))
        return web.json_response({"message": "✅ Clan-Konto gespeichert."})
 
    async def edit_item(self, request):
        guild, member = await self.member_of(request)
        if not member or not await is_staff(member):
            return fail("Nur das Team darf Items ändern.", 403)
        try:
            d = await request.json()
            name, action, stock = str(d["name"]).strip()[:60], d.get("action", "set"), int(d.get("stock", 0))
            desc = str(d.get("description", "")).strip()[:200] or None
        except Exception:
            return fail("Ungültige Anfrage.")
        row = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (GUILD_ID, name))
        lent = row["stock"] - await available(row["id"]) if row else 0
        if not name:
            return fail("Name fehlt.")
        if action == "delete":
            if not row:
                return fail("Item nicht gefunden.", 404)
            if lent:
                return fail("Das Item ist noch verliehen.")
            await db.execute("DELETE FROM items WHERE id=?", (row["id"],))
            text = f"🗑 {name} gelöscht."
        elif not lent <= stock <= 100000:
            return fail(f"Ungültiger Bestand (aktuell {lent}× verliehen).")
        elif row:
            await db.execute("UPDATE items SET stock=?, description=? WHERE id=?", (stock, desc, row["id"]))
            text = f"✅ {name} aktualisiert."
        else:
            await db.execute("INSERT INTO items (guild_id, name, stock, description) VALUES (?,?,?,?)",
                             (GUILD_ID, name, stock, desc))
            text = f"✅ {name} hinzugefügt."
        await refresh_catalog(guild)
        return web.json_response({"message": text})
 
    async def login(self, request):
        if not (CLIENT_ID and CLIENT_SECRET and PUBLIC_URL):
            return web.Response(text="Login ist noch nicht eingerichtet.", status=503)
        state = secrets.token_urlsafe(16)
        redirect = web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode({
            "client_id": CLIENT_ID, "response_type": "code", "scope": "identify",
            "redirect_uri": PUBLIC_URL + "/callback", "state": state}))
        redirect.set_cookie("st", state, max_age=600, httponly=True, samesite="Lax")
        raise redirect
 
    async def callback(self, request):
        if "code" not in request.query or request.query.get("state") != request.cookies.get("st"):
            return web.Response(text="Login fehlgeschlagen. Bitte erneut versuchen.", status=400)
        async with ClientSession() as http:
            async with http.post("https://discord.com/api/oauth2/token", data={
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "authorization_code",
                    "code": request.query["code"], "redirect_uri": PUBLIC_URL + "/callback"}) as r:
                token = (await r.json()).get("access_token")
            if not token:
                return web.Response(text="Login fehlgeschlagen (Token).", status=400)
            async with http.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token}"}) as r:
                u = await r.json()
        avatar = f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png?size=64" if u.get("avatar") else ""
        redirect = web.HTTPFound("/#verleih")
        redirect.set_cookie("s", sign({"id": u["id"], "username": u["username"], "avatar": avatar,
                                       "name": u.get("global_name") or u["username"]}),
                            max_age=604800, httponly=True, samesite="Lax", secure=PUBLIC_URL.startswith("https"))
        redirect.del_cookie("st")
        raise redirect
 
    async def logout(self, request):
        redirect = web.HTTPFound("/")
        redirect.del_cookie("s")
        raise redirect
 
    async def members(self, request):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return web.json_response([])
 
        async def roles_of(keys):  # Name und Farbe kommen direkt von der Discord-Rolle
            out = []
            for k in keys:
                role = await get_role(guild, k)
                colour = role.colour.value if role and role.colour.value else ROLE_SPECS[k][1]
                out.append((role, role.name if role else ROLE_SPECS[k][0], "#%06x" % colour))
            return out
 
        ranks = await roles_of(("leader", "officer", "builder_lead", "lender", "member", "recruit"))
        skills = await roles_of(("farmer", "builder", "miner"))
        groups = [{"label": name, "color": color, "members": []} for _, name, color in ranks]
        for m in sorted(guild.members, key=lambda x: x.display_name.lower()):
            if m.bot:
                continue
            for (role, _, _), group in zip(ranks, groups):
                if role and role in m.roles:
                    skill = next(({"name": n, "color": c} for r, n, c in skills if r and r in m.roles), None)
                    group["members"].append({"name": m.display_name, "skill": skill,
                                             "avatar": m.display_avatar.with_size(64).url})
                    break
        return web.json_response(groups)
 
    async def stats(self, request):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return web.json_response({"clan": 0, "leiher": 0})
        clan_roles = [await get_role(guild, k) for k in ("leader", "officer", "builder_lead", "member", "recruit")]
        clan_roles = [r for r in clan_roles if r]
        borrower = await get_role(guild, "borrower")
        people = [m for m in guild.members if not m.bot]
        return web.json_response({
            "clan": sum(1 for m in people if any(r in m.roles for r in clan_roles)),
            "leiher": sum(1 for m in people if borrower and borrower in m.roles)})
 
    async def rules(self, request):
        text, guild = "", self.bot.get_guild(GUILD_ID)
        channel, mid = (await get_ch(guild, "rules") if guild else None), await db.get_setting(GUILD_ID, "msg_rules")
        if channel and mid:
            try:
                text = (await channel.fetch_message(int(mid))).embeds[0].description or ""
            except Exception:
                pass
        return web.json_response({"rules": [l.strip() for l in text.split("\n") if l.strip() and not l.startswith("*")]})
 
    async def borrow(self, request):
        user = self.user(request)
        if not user:
            return fail("Bitte melde dich zuerst an.", 401)
        try:
            data = await request.json()
            name, amount, days = str(data["item"]), int(data["menge"]), int(data["tage"])
        except Exception:
            return fail("Ungültige Anfrage.")
        guild = self.bot.get_guild(GUILD_ID)
        member = guild.get_member(int(user["id"])) if guild else None
        if not member:
            return fail("Du bist nicht auf unserem Discord-Server.", 403)
        role = await get_role(guild, "borrower")
        if role not in member.roles and not await is_staff(member):
            return fail("Dir fehlt die Leiher-Rolle. Hol sie dir im Discord im Kanal #rollen.", 403)
        if not (1 <= amount <= 1000 and 1 <= days <= 60):
            return fail("Menge oder Tage ungültig.")
        item = await db.fetchone("SELECT * FROM items WHERE guild_id=? AND name=?", (GUILD_ID, name))
        if not item:
            return fail("Item nicht gefunden.", 404)
        open_n = (await db.fetchone("SELECT COUNT(*) AS n FROM loans WHERE guild_id=? AND user_id=? AND status IN ('pending','active')",
                                    (GUILD_ID, member.id)))["n"]
        if open_n >= MAX_OPEN_LOANS:
            return fail(f"Du hast bereits {open_n} offene Leihen (Maximum {MAX_OPEN_LOANS}).")
        if await available(item["id"]) < amount:
            return fail("Davon ist nicht genug verfügbar.")
        team = await get_ch(guild, "loan_team")
        if not team:
            return fail("Das Leihhaus ist gerade nicht erreichbar.", 503)
        loan_id = await db.execute(
            "INSERT INTO loans (guild_id, user_id, item_id, amount, days, status, requested_at, note) "
            "VALUES (?,?,?,?,?,'pending',?,'Über die Website')",
            (GUILD_ID, member.id, item["id"], amount, days, loan_now().isoformat()))
        loan = await db.fetchone("SELECT * FROM loans WHERE id=?", (loan_id,))
        lender = await get_role(guild, "lender")
        msg = await team.send(content=lender.mention if lender else None, embed=await loan_embed(loan),
                              view=loan_view(loan_id, "pending"), allowed_mentions=discord.AllowedMentions(roles=True))
        await db.execute("UPDATE loans SET message_id=? WHERE id=?", (msg.id, loan_id))
        return web.json_response({"message": f"✅ Anfrage #{loan_id} gesendet! Du bekommst eine DM, sobald sie bearbeitet wurde."})
 
    async def apply(self, request):
        ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
        now = time.time()
        hits[ip] = [t for t in hits.get(ip, []) if now - t < 3600]
        if len(hits[ip]) >= 3:
            return fail("Zu viele Bewerbungen. Versuche es später erneut.", 429)
        try:
            data = await request.json()
        except Exception:
            return fail("Ungültige Anfrage.")
        if data.get("website"):  # Honeypot für Bots
            return web.json_response({"message": "Danke!"})
 
        def clean(key, size):
            return str(data.get(key, "")).strip()[:size]
 
        mc, dc, role = clean("minecraft", 32), clean("discord", 40), clean("rolle", 10)
        exp, why = clean("erfahrung", 800), clean("motivation", 800)
        if not (mc and dc and why):
            return fail("Bitte Minecraft-Name, Discord-Name und Motivation ausfüllen.")
        guild = self.bot.get_guild(GUILD_ID)
        channel = await get_ch(guild, "team") if guild else None
        if not channel:
            return fail("Bewerbungen sind gerade nicht möglich.", 503)
        hits[ip].append(now)
        app_id = await db.execute(
            "INSERT INTO applications (guild_id, minecraft, discord_name, role, experience, motivation, status, created_at) "
            "VALUES (?,?,?,?,?,?,'pending',datetime('now'))",
            (GUILD_ID, mc, dc, role if role in ROLES else "Egal", exp, why))
        row = await db.fetchone("SELECT * FROM applications WHERE id=?", (app_id,))
        view = discord.ui.View(timeout=None)
        view.add_item(AppButton("accept", app_id))
        view.add_item(AppButton("decline", app_id))
        officer = await get_role(guild, "officer")
        msg = await channel.send(content=officer.mention if officer else None, embed=app_embed(row), view=view,
                                 allowed_mentions=discord.AllowedMentions(roles=True))
        await db.execute("UPDATE applications SET message_id=? WHERE id=?", (msg.id, app_id))
        return web.json_response({"message": "✅ Bewerbung gesendet! Wir melden uns bei dir auf Discord."})
 
 
async def setup(bot):
