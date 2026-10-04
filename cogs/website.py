import html
import os
import time
 
import discord
from aiohttp import web
from discord.ext import commands
 
import db
from cogs.loans import available
from utils import get_ch, get_role, is_staff
 
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CLAN = html.escape(os.getenv("CLAN_NAME", "Unser Clan"))
ROLES = ("Farmer", "Builder", "Miner", "Egal")
COLORS = {"pending": 0xF1C40F, "accepted": 0x2ECC71, "declined": 0xE74C3C}
hits = {}
 
PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__CLAN__</title><style>
:root{--bg:#14171c;--card:#1f242c;--line:#323a46;--fg:#e8edf2;--mut:#8b96a5;--ok:#4ade80;--bad:#f87171}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
header{padding:48px 20px;text-align:center;border-bottom:3px solid var(--line)}h1{margin:0;font-size:2.4rem}header p{color:var(--mut);margin:6px 0 0}
main{max-width:960px;margin:auto;padding:8px 20px 60px}h2{margin-top:40px}
input,select,textarea,button{font:inherit;color:inherit;background:var(--card);border:2px solid var(--line);padding:10px 12px;width:100%}
button{background:var(--ok);color:#052e16;font-weight:700;cursor:pointer;border-color:var(--ok)}button:disabled{opacity:.5}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:14px}
.item{background:var(--card);border:2px solid var(--line);padding:14px}.item b{display:block}.item small{color:var(--mut)}
.bar{height:8px;background:var(--line);margin:10px 0 6px}.bar i{display:block;height:100%;background:var(--ok)}.out .bar i{background:var(--bad)}
form{display:grid;gap:12px;margin-top:14px}label{display:grid;gap:4px;color:var(--mut);font-size:.9rem}
#msg{min-height:1.5em}.hp{position:absolute;left:-9999px}
</style></head><body>
<header><h1>⛏️ __CLAN__</h1><p>Leihhaus &amp; Bewerbung</p></header><main>
<h2>📦 Leihhaus</h2><input id="q" placeholder="Item suchen …"><div id="items" class="grid"></div>
<h2>📝 Bewerben</h2>
<form id="f">
<label>Minecraft-Name<input name="minecraft" maxlength="32" required></label>
<label>Discord-Name (z. B. max123)<input name="discord" maxlength="40" required></label>
<label>Wunschrolle<select name="rolle"><option>Farmer</option><option>Builder</option><option>Miner</option><option>Egal</option></select></label>
<label>Erfahrung<textarea name="erfahrung" rows="3" maxlength="800"></textarea></label>
<label>Warum möchtest du zu uns?<textarea name="motivation" rows="4" maxlength="800" required></textarea></label>
<input class="hp" name="website" tabindex="-1" autocomplete="off">
<button>Bewerbung absenden</button><div id="msg"></div></form></main>
<script>
const $=s=>document.querySelector(s);let items=[];
function draw(){const q=$('#q').value.toLowerCase(),box=$('#items');box.replaceChildren();
const list=items.filter(i=>i.name.toLowerCase().includes(q));
if(!list.length){box.textContent='Keine Items gefunden.';return}
for(const i of list){const d=document.createElement('div');d.className='item'+(i.available>0?'':' out');
const b=document.createElement('b');b.textContent=i.name;
const bar=document.createElement('div');bar.className='bar';const p=document.createElement('i');
p.style.width=(i.stock?100*i.available/i.stock:0)+'%';bar.append(p);
const s=document.createElement('small');
s.textContent=(i.available>0?'🟢 ':'🔴 ')+i.available+' / '+i.stock+' verfügbar'+(i.description?' · '+i.description:'');
d.append(b,bar,s);box.append(d)}}
async function load(){try{items=await(await fetch('/api/items')).json();draw()}catch(e){}}
$('#q').oninput=draw;load();setInterval(load,30000);
$('#f').onsubmit=async e=>{e.preventDefault();const btn=$('#f button'),m=$('#msg');btn.disabled=true;m.textContent='Sende …';
try{const r=await fetch('/api/bewerbung',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});const j=await r.json();
m.textContent=j.message;if(r.ok)e.target.reset()}catch(x){m.textContent='Fehler beim Senden.'}btn.disabled=false};
</script></body></html>""".replace("__CLAN__", CLAN)
 
 
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
                        web.post("/api/bewerbung", self.apply)])
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
 
    async def index(self, request):
        return web.Response(text=PAGE, content_type="text/html")
 
    async def items(self, request):
        rows = await db.fetchall("SELECT * FROM items WHERE guild_id=? ORDER BY name", (GUILD_ID,))
        return web.json_response([
            {"name": r["name"], "stock": r["stock"], "available": await available(r["id"]),
             "description": r["description"] or ""} for r in rows])
 
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
    await bot.add_cog(Website(bot))
