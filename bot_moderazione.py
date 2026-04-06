import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import asyncio
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────
#  CONFIGURAZIONE - MODIFICA SOLO QUESTA PARTE
# ─────────────────────────────────────────
TOKEN    = "IL_TUO_TOKEN_QUI"
OWNER_IDS = [1222812045184073750, 1487162734943666399, 1406630448381165588]

# ─────────────────────────────────────────
#  FILE DI SALVATAGGIO
# ─────────────────────────────────────────
CONFIG_FILE = "config.json"
WARNS_FILE  = "warns.json"

# ─────────────────────────────────────────
#  ANTI-SPAM TRACKER
# ─────────────────────────────────────────
spam_tracker = defaultdict(list)
SPAM_LIMIT   = 5
SPAM_WINDOW  = 5

# ─────────────────────────────────────────
#  ANTINUKE TRACKER
# ─────────────────────────────────────────
nuke_tracker = defaultdict(lambda: defaultdict(list))
NUKE_LIMIT   = 3
NUKE_WINDOW  = 10

# ─────────────────────────────────────────
#  REGEX LINK DISCORD
# ─────────────────────────────────────────
DISCORD_INVITE_REGEX = re.compile(
    r"(discord\.gg|discord\.com\/invite|discordapp\.com\/invite)\/\S+",
    re.IGNORECASE
)

# ─────────────────────────────────────────
#  UTILITY
# ─────────────────────────────────────────
def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS

def has_perm(interaction: discord.Interaction, perm: str) -> bool:
    """Controlla se l'utente è owner, ha il permesso Discord, o ha un ruolo abilitato."""
    if is_owner(interaction):
        return True
    if getattr(interaction.user.guild_permissions, perm, False):
        return True
    # Controlla ruoli custom
    config = load_json(CONFIG_FILE)
    allowed_roles = config.get(str(interaction.guild.id), {}).get("roles", {}).get(perm, [])
    user_role_ids = [r.id for r in interaction.user.roles]
    return any(rid in user_role_ids for rid in allowed_roles)

def parse_duration(duration: str):
    match = re.fullmatch(r"(\d+)(s|m|h|d)", duration.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

def format_duration(seconds: int) -> str:
    if seconds < 60:      return f"{seconds} secondi"
    elif seconds < 3600:  return f"{seconds // 60} minuti"
    elif seconds < 86400: return f"{seconds // 3600} ore"
    else:                 return f"{seconds // 86400} giorni"

# ─────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─────────────────────────────────────────
#  FUNZIONE LOG
# ─────────────────────────────────────────
async def send_log(guild, action, moderator, target, reason=None, extra=None):
    config = load_json(CONFIG_FILE)
    guild_id = str(guild.id)
    if guild_id not in config or "canale_logs" not in config[guild_id]:
        return
    canale = guild.get_channel(config[guild_id]["canale_logs"])
    if canale is None:
        return

    colori = {
        "BAN": discord.Color.red(), "UNBAN": discord.Color.green(),
        "KICK": discord.Color.orange(), "MUTE": discord.Color.dark_orange(),
        "UNMUTE": discord.Color.teal(), "WARN": discord.Color.yellow(),
        "CLEAR": discord.Color.blurple(), "LOCK": discord.Color.dark_red(),
        "UNLOCK": discord.Color.dark_green(), "RIMUOVI RUOLO": discord.Color.purple(),
        "AUTO-MUTE": discord.Color.dark_orange(), "AUTO-BAN": discord.Color.dark_red(),
        "AUTOMOD": discord.Color.gold(), "ANTINUKE": discord.Color.from_rgb(255, 0, 80),
        "MUTE TEMP": discord.Color.dark_orange(), "BAN ALL": discord.Color.dark_red(),
        "ANTILINK": discord.Color.gold(),
    }
    emoji = {
        "BAN": "🔨", "UNBAN": "✅", "KICK": "👢", "MUTE": "🔇",
        "UNMUTE": "🔊", "WARN": "⚠️", "CLEAR": "🗑️", "LOCK": "🔒",
        "UNLOCK": "🔓", "RIMUOVI RUOLO": "🎭", "AUTO-MUTE": "🤖🔇",
        "AUTO-BAN": "🤖🔨", "AUTOMOD": "🛡️", "ANTINUKE": "🚨",
        "MUTE TEMP": "⏱️🔇", "BAN ALL": "☢️", "ANTILINK": "🔗",
    }

    embed = discord.Embed(
        title=f"{emoji.get(action, '📋')} {action}",
        color=colori.get(action, discord.Color.blurple()),
        timestamp=datetime.utcnow()
    )
    if isinstance(target, (discord.Member, discord.User)):
        embed.add_field(name="👤 Utente", value=f"{target.mention} (`{target.id}`)", inline=True)
    else:
        embed.add_field(name="🎯 Target", value=str(target), inline=True)
    if moderator:
        embed.add_field(name="🛡️ Moderatore", value=moderator.mention, inline=True)
    if reason:
        embed.add_field(name="📝 Motivo", value=reason, inline=False)
    if extra:
        for k, v in extra.items():
            embed.add_field(name=k, value=v, inline=True)
    embed.set_footer(text=f"Server: {guild.name}")
    await canale.send(embed=embed)

# ─────────────────────────────────────────
#  MUTED ROLE
# ─────────────────────────────────────────
async def get_or_create_muted_role(guild):
    config = load_json(CONFIG_FILE)
    guild_id = str(guild.id)
    muted_role_id = config.get(guild_id, {}).get("muted_role")
    muted_role = guild.get_role(muted_role_id) if muted_role_id else discord.utils.get(guild.roles, name="Muted")
    if muted_role is None:
        muted_role = await guild.create_role(name="Muted")
        for channel in guild.channels:
            await channel.set_permissions(muted_role, send_messages=False, speak=False, send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
        config.setdefault(guild_id, {})["muted_role"] = muted_role.id
        save_json(CONFIG_FILE, config)
    return muted_role

# ─────────────────────────────────────────
#  WARN AUTOMATICO
# ─────────────────────────────────────────
async def aggiungi_warn(guild, moderator, member, reason):
    warns = load_json(WARNS_FILE)
    guild_id = str(guild.id)
    user_id  = str(member.id)
    warns.setdefault(guild_id, {}).setdefault(user_id, [])
    warns[guild_id][user_id].append({
        "reason": reason,
        "moderator": str(moderator.id),
        "timestamp": str(datetime.utcnow())
    })
    save_json(WARNS_FILE, warns)
    num = len(warns[guild_id][user_id])

    if num == 2:
        muted_role = await get_or_create_muted_role(guild)
        await member.add_roles(muted_role)
        await send_log(guild, "AUTO-MUTE", bot.user, member,
                       reason="Raggiunto il limite di 2 warn",
                       extra={"⚠️ Warn totali": str(num)})
    elif num >= 5:
        await member.ban(reason="Raggiunto il limite di 5 warn")
        await send_log(guild, "AUTO-BAN", bot.user, member,
                       reason="Raggiunto il limite di 5 warn",
                       extra={"⚠️ Warn totali": str(num)})
    return num

# ─────────────────────────────────────────
#  AUTOMOD
# ─────────────────────────────────────────
async def automod_check(message: discord.Message):
    if message.author.bot or not isinstance(message.author, discord.Member):
        return
    if message.author.id == OWNER_ID or message.author.guild_permissions.administrator:
        return

    config = load_json(CONFIG_FILE)
    guild_id = str(message.guild.id)
    automod_cfg = config.get(guild_id, {}).get("automod", {})

    # ── ANTILINK ──────────────────────────────────────
    antilink_cfg = config.get(guild_id, {}).get("antilink", {})
    if antilink_cfg.get("enabled", False):
        whitelist_channels = antilink_cfg.get("whitelist", [])
        if message.channel.id not in whitelist_channels:
            if DISCORD_INVITE_REGEX.search(message.content):
                try:
                    await message.delete()
                except Exception:
                    pass
                await send_log(message.guild, "ANTILINK", bot.user, message.author,
                               reason="Link Discord rilevato e cancellato",
                               extra={"📌 Canale": message.channel.mention})
                try:
                    await message.channel.send(
                        f"🔗 {message.author.mention} i link Discord non sono consentiti qui!",
                        delete_after=5
                    )
                except Exception:
                    pass
                await aggiungi_warn(message.guild, bot.user, message.author, "[ANTILINK] Invio link Discord")
                return

    # ── AUTOMOD ───────────────────────────────────────
    if not automod_cfg.get("enabled", False):
        return

    motivo = None

    if automod_cfg.get("bad_words", False):
        bad_words = automod_cfg.get("bad_words_list", [])
        content_lower = message.content.lower()
        for word in bad_words:
            if word.lower() in content_lower:
                motivo = f"Parola vietata: `{word}`"
                break

    if not motivo and automod_cfg.get("antispam", False):
        now = datetime.utcnow()
        uid = str(message.author.id)
        spam_limit  = automod_cfg.get("spam_limit",  SPAM_LIMIT)
        spam_window = automod_cfg.get("spam_window", SPAM_WINDOW)
        spam_mute_duration = automod_cfg.get("spam_mute_duration", None)
        spam_tracker[uid] = [t for t in spam_tracker[uid] if (now - t).total_seconds() < spam_window]
        spam_tracker[uid].append(now)
        if len(spam_tracker[uid]) >= spam_limit:
            motivo = f"Spam rilevato ({spam_limit} messaggi in {spam_window}s)"
            spam_tracker[uid] = []
            # Mute automatico con durata configurabile
            muted_role = await get_or_create_muted_role(message.guild)
            if muted_role not in message.author.roles:
                await message.author.add_roles(muted_role, reason=f"[AUTOMOD] {motivo}")
                if spam_mute_duration:
                    secondi_mute = parse_duration(spam_mute_duration)
                    if secondi_mute:
                        async def unmute_after(member, role, secs):
                            await asyncio.sleep(secs)
                            if role in member.roles:
                                await member.remove_roles(role, reason="Mute antispam scaduto")
                                await send_log(message.guild, "UNMUTE", bot.user, member, reason="Mute antispam scaduto")
                        asyncio.create_task(unmute_after(message.author, muted_role, secondi_mute))
            return  # Esce subito dopo il mute, senza passare per il warn generico

    if not motivo and automod_cfg.get("anticaps", False):
        content = message.content
        if len(content) >= 8:
            upper = sum(1 for c in content if c.isupper())
            if upper / len(content) > 0.7:
                motivo = "Messaggio in eccessivo maiuscolo"

    if not motivo and automod_cfg.get("antimentions", False):
        max_mentions = automod_cfg.get("max_mentions", 5)
        if len(message.mentions) >= max_mentions:
            motivo = f"Troppe mention ({len(message.mentions)})"

    if motivo:
        try:
            await message.delete()
        except Exception:
            pass
        await send_log(message.guild, "AUTOMOD", bot.user, message.author,
                       reason=motivo, extra={"📌 Canale": message.channel.mention})
        try:
            await message.channel.send(
                f"⚠️ {message.author.mention} messaggio rimosso: **{motivo}**",
                delete_after=5
            )
        except Exception:
            pass
        await aggiungi_warn(message.guild, bot.user, message.author, f"[AUTOMOD] {motivo}")

# ─────────────────────────────────────────
#  ANTINUKE
# ─────────────────────────────────────────
async def nuke_action(guild, user, action_type):
    config = load_json(CONFIG_FILE)
    if not config.get(str(guild.id), {}).get("antinuke", False):
        return
    if user.id == OWNER_ID or user.bot:
        return

    now = datetime.utcnow()
    uid = str(user.id)
    gid = str(guild.id)
    nuke_tracker[gid][uid] = [t for t in nuke_tracker[gid][uid] if (now - t).total_seconds() < NUKE_WINDOW]
    nuke_tracker[gid][uid].append(now)

    if len(nuke_tracker[gid][uid]) >= NUKE_LIMIT:
        nuke_tracker[gid][uid] = []
        await send_log(guild, "ANTINUKE", bot.user, user,
                       reason=f"{NUKE_LIMIT} azioni pericolose in {NUKE_WINDOW}s",
                       extra={"🚨 Azione": action_type})
        try:
            await guild.ban(user, reason=f"[ANTINUKE] {action_type}")
        except Exception:
            pass

# ─────────────────────────────────────────
#  VIEW CONFERMA NUKE
# ─────────────────────────────────────────
class NukeView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=30)
        self.guild_id = guild_id

    @discord.ui.button(label="☢️ CONFERMA NUKE", style=discord.ButtonStyle.danger)
    async def conferma(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            await interaction.response.send_message("❌ Non autorizzato.", ephemeral=True)
            return
        self.stop()
        await interaction.response.send_message(
            embed=discord.Embed(
                title="☢️ NUKE IN CORSO",
                description="**FASE 1/3** — Ban di tutti i membri non admin...",
                color=discord.Color.dark_red()
            ),
            ephemeral=True
        )

        guild = interaction.guild
        bannati = 0
        errori_ban = 0

        # ── FASE 1: Ban massivo in parallelo ──────────────
        members = [m async for m in guild.fetch_members(limit=None)]
        ban_tasks = []
        for member in members:
            if member.bot or member.id in OWNER_IDS:
                continue
            if member.guild_permissions.administrator:
                continue
            ban_tasks.append(member.ban(reason="[NUKE] Eseguito dal possessore del bot"))

        results = await asyncio.gather(*ban_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                errori_ban += 1
            else:
                bannati += 1

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅ **FASE 1 completata** — Bannati: **{bannati}** | Errori: **{errori_ban}**\n⏳ **FASE 2/3** — Eliminazione canali...",
                color=discord.Color.dark_red()
            ),
            ephemeral=True
        )

        # ── FASE 2: Elimina tutti i canali ────────────────
        canali_eliminati = 0
        errori_canali = 0
        channel_tasks = [ch.delete(reason="[NUKE]") for ch in guild.channels]
        results2 = await asyncio.gather(*channel_tasks, return_exceptions=True)
        for r in results2:
            if isinstance(r, Exception):
                errori_canali += 1
            else:
                canali_eliminati += 1

        # ── FASE 3: Elimina tutti i ruoli ─────────────────
        ruoli_eliminati = 0
        errori_ruoli = 0
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            try:
                await role.delete(reason="[NUKE]")
                ruoli_eliminati += 1
            except Exception:
                errori_ruoli += 1

        try:
            await send_log(guild, "BAN ALL", interaction.user, guild,
                           reason="NUKE eseguito dal possessore",
                           extra={
                               "🔨 Bannati": str(bannati),
                               "🗑️ Canali eliminati": str(canali_eliminati),
                               "🎭 Ruoli eliminati": str(ruoli_eliminati)
                           })
        except Exception:
            pass

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.secondary)
    async def annulla(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.send_message("✅ Operazione annullata.", ephemeral=True)

# ─────────────────────────────────────────
#  EVENTI
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    try:
        synced = await tree.sync()
        print(f"✅ Bot online come {bot.user} | Comandi sincronizzati: {len(synced)}")
    except Exception as e:
        print(f"❌ Errore sincronizzazione: {e}")

@bot.event
async def on_message(message):
    await automod_check(message)
    await bot.process_commands(message)

@bot.event
async def on_guild_channel_delete(channel):
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        await nuke_action(channel.guild, entry.user, "Cancellazione canale")

@bot.event
async def on_guild_role_delete(role):
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        await nuke_action(role.guild, entry.user, "Cancellazione ruolo")

@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        await nuke_action(guild, entry.user, "Ban massivo")

@bot.event
async def on_member_remove(member):
    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        if entry.target.id == member.id:
            await nuke_action(member.guild, entry.user, "Kick massivo")

# ─────────────────────────────────────────
#  GESTIONE ERRORI
# ─────────────────────────────────────────
@tree.error
async def on_error(interaction: discord.Interaction, error):
    if is_owner(interaction):
        return
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Errore: {str(error)}", ephemeral=True)

# ═══════════════════════════════════════════════════════
#  COMANDI CONFIGURAZIONE
# ═══════════════════════════════════════════════════════

@tree.command(name="setlogs", description="Imposta il canale per i log di moderazione")
@app_commands.describe(canale="Canale dove inviare i log")
async def setlogs(interaction: discord.Interaction, canale: discord.TextChannel):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    config.setdefault(str(interaction.guild.id), {})["canale_logs"] = canale.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"✅ Log configurati in {canale.mention}.", color=discord.Color.green()),
        ephemeral=True
    )

# ─────────────────────────────────────────
#  /setrole - assegna ruoli ai comandi
# ─────────────────────────────────────────
PERM_CHOICES = [
    app_commands.Choice(name="Ban",             value="ban_members"),
    app_commands.Choice(name="Kick",            value="kick_members"),
    app_commands.Choice(name="Mute",            value="manage_roles"),
    app_commands.Choice(name="Warn / Clear",    value="manage_messages"),
    app_commands.Choice(name="Lock / Unlock",   value="manage_channels"),
    app_commands.Choice(name="Amministratore",  value="administrator"),
]

@tree.command(name="setrole", description="Assegna un ruolo che può usare un comando di moderazione")
@app_commands.describe(comando="Il comando da abilitare", ruolo="Il ruolo da abilitare")
@app_commands.choices(comando=PERM_CHOICES)
async def setrole(interaction: discord.Interaction, comando: str, ruolo: discord.Role):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    guild_id = str(interaction.guild.id)
    roles_cfg = config.setdefault(guild_id, {}).setdefault("roles", {})
    roles_cfg.setdefault(comando, [])
    if ruolo.id not in roles_cfg[comando]:
        roles_cfg[comando].append(ruolo.id)
    save_json(CONFIG_FILE, config)

    nome_comando = next((c.name for c in PERM_CHOICES if c.value == comando), comando)
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"✅ Il ruolo {ruolo.mention} può ora usare i comandi di **{nome_comando}**.",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

@tree.command(name="removerole", description="Rimuove un ruolo dai permessi di un comando")
@app_commands.describe(comando="Il comando", ruolo="Il ruolo da rimuovere")
@app_commands.choices(comando=PERM_CHOICES)
async def removerole(interaction: discord.Interaction, comando: str, ruolo: discord.Role):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    guild_id = str(interaction.guild.id)
    roles_cfg = config.get(guild_id, {}).get("roles", {})
    if ruolo.id in roles_cfg.get(comando, []):
        roles_cfg[comando].remove(ruolo.id)
        save_json(CONFIG_FILE, config)
    nome_comando = next((c.name for c in PERM_CHOICES if c.value == comando), comando)
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"✅ Ruolo {ruolo.mention} rimosso dai permessi di **{nome_comando}**.",
            color=discord.Color.orange()
        ),
        ephemeral=True
    )

@tree.command(name="listroles", description="Mostra i ruoli abilitati per ogni comando")
async def listroles(interaction: discord.Interaction):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    roles_cfg = config.get(str(interaction.guild.id), {}).get("roles", {})
    embed = discord.Embed(title="🎭 Ruoli abilitati per comando", color=discord.Color.blurple())
    for choice in PERM_CHOICES:
        role_ids = roles_cfg.get(choice.value, [])
        roles_str = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "Nessuno"
        embed.add_field(name=choice.name, value=roles_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─────────────────────────────────────────
#  ANTILINK COMANDI
# ─────────────────────────────────────────
@tree.command(name="antilink", description="Attiva o disattiva il blocco link Discord")
@app_commands.describe(stato="Attiva o disattiva")
@app_commands.choices(stato=[
    app_commands.Choice(name="Attiva",    value="on"),
    app_commands.Choice(name="Disattiva", value="off")
])
async def antilink(interaction: discord.Interaction, stato: str):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    config.setdefault(str(interaction.guild.id), {}).setdefault("antilink", {})["enabled"] = (stato == "on")
    save_json(CONFIG_FILE, config)
    emoji = "✅" if stato == "on" else "❌"
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"{emoji} Antilink **{'attivato' if stato == 'on' else 'disattivato'}**.",
            color=discord.Color.green() if stato == "on" else discord.Color.red()
        ),
        ephemeral=True
    )

@tree.command(name="antilink_whitelist", description="Aggiungi o rimuovi un canale dalla whitelist antilink")
@app_commands.describe(azione="Aggiungi o rimuovi", canale="Il canale")
@app_commands.choices(azione=[
    app_commands.Choice(name="Aggiungi", value="add"),
    app_commands.Choice(name="Rimuovi",  value="remove"),
    app_commands.Choice(name="Lista",    value="list")
])
async def antilink_whitelist(interaction: discord.Interaction, azione: str, canale: discord.TextChannel = None):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    guild_id = str(interaction.guild.id)
    whitelist = config.setdefault(guild_id, {}).setdefault("antilink", {}).setdefault("whitelist", [])

    if azione == "add" and canale:
        if canale.id not in whitelist:
            whitelist.append(canale.id)
        msg = f"✅ {canale.mention} aggiunto alla whitelist antilink."
    elif azione == "remove" and canale:
        if canale.id in whitelist:
            whitelist.remove(canale.id)
        msg = f"✅ {canale.mention} rimosso dalla whitelist antilink."
    elif azione == "list":
        canali = " ".join(f"<#{cid}>" for cid in whitelist) if whitelist else "Nessuno"
        msg = f"📋 Canali in whitelist: {canali}"
    else:
        msg = "❌ Specifica un canale."

    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(msg, ephemeral=True)

# ─────────────────────────────────────────
#  AUTOMOD COMANDI
# ─────────────────────────────────────────
@tree.command(name="automod_abilita", description="Abilita o disabilita l'automoderazione")
@app_commands.describe(stato="Attiva o disattiva")
@app_commands.choices(stato=[
    app_commands.Choice(name="Attiva",    value="on"),
    app_commands.Choice(name="Disattiva", value="off")
])
async def automod_abilita(interaction: discord.Interaction, stato: str):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    config.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})["enabled"] = (stato == "on")
    save_json(CONFIG_FILE, config)
    emoji = "✅" if stato == "on" else "❌"
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"{emoji} Automoderazione **{'attivata' if stato == 'on' else 'disattivata'}**.",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

@tree.command(name="automod_configura", description="Configura i moduli dell'automoderazione")
@app_commands.describe(
    antispam="Blocca lo spam",
    anticaps="Blocca caps lock",
    antimentions="Blocca mention eccessive",
    max_mentions="Numero massimo di mention"
)
async def automod_configura(interaction: discord.Interaction,
    antispam: bool = None, anticaps: bool = None,
    antimentions: bool = None, max_mentions: int = None):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    cfg = config.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
    if antispam is not None:     cfg["antispam"]     = antispam
    if anticaps is not None:     cfg["anticaps"]     = anticaps
    if antimentions is not None: cfg["antimentions"] = antimentions
    if max_mentions is not None: cfg["max_mentions"] = max_mentions
    save_json(CONFIG_FILE, config)

    embed = discord.Embed(title="🛡️ Automod configurata", color=discord.Color.gold())
    embed.add_field(name="Anti-Spam",    value="✅" if cfg.get("antispam")     else "❌", inline=True)
    embed.add_field(name="Anti-Caps",    value="✅" if cfg.get("anticaps")     else "❌", inline=True)
    embed.add_field(name="Anti-Mention", value="✅" if cfg.get("antimentions") else "❌", inline=True)
    embed.add_field(name="Max Mention",  value=str(cfg.get("max_mentions", 5)),           inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="automod_parole", description="Aggiungi o rimuovi parole vietate")
@app_commands.describe(azione="Azione", parola="Parola")
@app_commands.choices(azione=[
    app_commands.Choice(name="Aggiungi", value="add"),
    app_commands.Choice(name="Rimuovi",  value="remove"),
    app_commands.Choice(name="Lista",    value="list")
])
async def automod_parole(interaction: discord.Interaction, azione: str, parola: str = None):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    cfg   = config.setdefault(str(interaction.guild.id), {}).setdefault("automod", {})
    words = cfg.get("bad_words_list", [])

    if azione == "add" and parola:
        if parola.lower() not in words:
            words.append(parola.lower())
            cfg["bad_words"] = True
        msg = f"✅ Parola `{parola}` aggiunta."
    elif azione == "remove" and parola:
        if parola.lower() in words:
            words.remove(parola.lower())
        msg = f"✅ Parola `{parola}` rimossa."
    elif azione == "list":
        msg = "📋 Parole vietate: " + (", ".join(f"`{w}`" for w in words) if words else "nessuna")
    else:
        msg = "❌ Specifica una parola."

    cfg["bad_words_list"] = words
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(msg, ephemeral=True)

# ─────────────────────────────────────────
#  ANTINUKE COMANDO
# ─────────────────────────────────────────
@tree.command(name="antinuke", description="Attiva o disattiva l'antinuke")
@app_commands.describe(stato="Attiva o disattiva")
@app_commands.choices(stato=[
    app_commands.Choice(name="Attiva",    value="on"),
    app_commands.Choice(name="Disattiva", value="off")
])
async def antinuke(interaction: discord.Interaction, stato: str):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    config.setdefault(str(interaction.guild.id), {})["antinuke"] = (stato == "on")
    save_json(CONFIG_FILE, config)
    emoji = "✅" if stato == "on" else "❌"
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"🚨 Antinuke **{'attivato' if stato == 'on' else 'disattivato'}**.\n"
                        f"Protezione: {NUKE_LIMIT} azioni pericolose in {NUKE_WINDOW}s → ban automatico.",
            color=discord.Color.green() if stato == "on" else discord.Color.red()
        ),
        ephemeral=True
    )

# ═══════════════════════════════════════════════════════
#  COMANDI DI MODERAZIONE
# ═══════════════════════════════════════════════════════

@tree.command(name="ban", description="Banna un utente dal server")
@app_commands.describe(member="Utente da bannare", reason="Motivo")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "ban_members"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔨 {member.mention} bannato. Motivo: {reason}", color=discord.Color.red()),
        ephemeral=True
    )
    await send_log(interaction.guild, "BAN", interaction.user, member, reason=reason)

@tree.command(name="nuke", description="☢️ Nuke del server (solo owner)")
async def nuke(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Non autorizzato.", ephemeral=True)
        return
    embed = discord.Embed(
        title="☢️ CONFERMA NUKE SERVER",
        description="Stai per eseguire un **NUKE COMPLETO** del server:\n\n"
                    "**FASE 1** — Ban di tutti i membri non admin\n"
                    "**FASE 2** — Eliminazione di tutti i canali\n"
                    "**FASE 3** — Eliminazione di tutti i ruoli\n\n"
                    "⚠️ Questa azione è **IRREVERSIBILE**. Sei sicuro?",
        color=discord.Color.dark_red()
    )
    await interaction.response.send_message(embed=embed, view=NukeView(interaction.guild.id), ephemeral=True)

@tree.command(name="unban", description="Rimuove il ban a un utente tramite ID")
@app_commands.describe(user_id="ID dell'utente", reason="Motivo")
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "ban_members"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ {user.mention} sbannato.", color=discord.Color.green()),
            ephemeral=True
        )
        await send_log(interaction.guild, "UNBAN", interaction.user, user, reason=reason)
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)

@tree.command(name="kick", description="Espelle un utente dal server")
@app_commands.describe(member="Utente da kickare", reason="Motivo")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "kick_members"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    await member.kick(reason=reason)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"👢 {member.mention} espulso. Motivo: {reason}", color=discord.Color.orange()),
        ephemeral=True
    )
    await send_log(interaction.guild, "KICK", interaction.user, member, reason=reason)

@tree.command(name="mute", description="Muta un utente permanentemente")
@app_commands.describe(member="Utente da mutare", reason="Motivo")
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_roles"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    muted_role = await get_or_create_muted_role(interaction.guild)
    await member.add_roles(muted_role, reason=reason)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔇 {member.mention} mutato. Motivo: {reason}", color=discord.Color.dark_orange()),
        ephemeral=True
    )
    await send_log(interaction.guild, "MUTE", interaction.user, member, reason=reason)

@tree.command(name="mutemp", description="Muta un utente per un tempo specifico (es. 10m, 2h, 1d)")
@app_commands.describe(member="Utente da mutare", durata="Durata (es. 10m, 2h, 1d)", reason="Motivo")
async def mutemp(interaction: discord.Interaction, member: discord.Member, durata: str, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_roles"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    secondi = parse_duration(durata)
    if secondi is None:
        await interaction.response.send_message("❌ Formato non valido. Usa: `10s`, `5m`, `2h`, `1d`", ephemeral=True)
        return
    muted_role = await get_or_create_muted_role(interaction.guild)
    await member.add_roles(muted_role, reason=reason)
    durata_str = format_duration(secondi)
    await interaction.response.send_message(
        embed=discord.Embed(
            description=f"⏱️🔇 {member.mention} mutato per **{durata_str}**. Motivo: {reason}",
            color=discord.Color.dark_orange()
        ),
        ephemeral=True
    )
    await send_log(interaction.guild, "MUTE TEMP", interaction.user, member,
                   reason=reason, extra={"⏱️ Durata": durata_str})
    await asyncio.sleep(secondi)
    if muted_role in member.roles:
        await member.remove_roles(muted_role, reason="Mute temporaneo scaduto")
        await send_log(interaction.guild, "UNMUTE", bot.user, member, reason="Mute temporaneo scaduto")

@tree.command(name="unmute", description="Rimuove il mute a un utente")
@app_commands.describe(member="Utente da smutare", reason="Motivo")
async def unmute(interaction: discord.Interaction, member: discord.Member, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_roles"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    config = load_json(CONFIG_FILE)
    muted_role_id = config.get(str(interaction.guild.id), {}).get("muted_role")
    muted_role = interaction.guild.get_role(muted_role_id) if muted_role_id else discord.utils.get(interaction.guild.roles, name="Muted")
    if muted_role and muted_role in member.roles:
        await member.remove_roles(muted_role, reason=reason)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🔊 {member.mention} smutato.", color=discord.Color.teal()),
            ephemeral=True
        )
        await send_log(interaction.guild, "UNMUTE", interaction.user, member, reason=reason)
    else:
        await interaction.response.send_message("❌ Questo utente non è mutato.", ephemeral=True)

@tree.command(name="warn", description="Avvisa un utente")
@app_commands.describe(member="Utente da avvisare", reason="Motivo")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_messages"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    num = await aggiungi_warn(interaction.guild, interaction.user, member, reason)
    await send_log(interaction.guild, "WARN", interaction.user, member,
                   reason=reason, extra={"⚠️ Warn totali": str(num)})
    msg = f"⚠️ {member.mention} ha ricevuto un warn. Motivo: {reason}\nWarn totali: **{num}**"
    if num == 2:   msg += "\n🔇 L'utente è stato automaticamente **mutato**!"
    elif num >= 5: msg += "\n🔨 L'utente è stato automaticamente **bannato**!"
    await interaction.followup.send(
        embed=discord.Embed(description=msg, color=discord.Color.yellow()), ephemeral=True
    )

@tree.command(name="warns", description="Visualizza i warn di un utente")
@app_commands.describe(member="Utente di cui vedere i warn")
async def warns(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction, "manage_messages"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    warns_data = load_json(WARNS_FILE)
    user_warns = warns_data.get(str(interaction.guild.id), {}).get(str(member.id), [])
    if not user_warns:
        await interaction.response.send_message(f"✅ {member.mention} non ha warn.", ephemeral=True)
        return
    embed = discord.Embed(title=f"⚠️ Warn di {member.display_name}", color=discord.Color.yellow())
    for i, w in enumerate(user_warns, 1):
        mod = interaction.guild.get_member(int(w["moderator"]))
        embed.add_field(
            name=f"Warn #{i}",
            value=f"**Motivo:** {w['reason']}\n**Moderatore:** {mod.display_name if mod else 'Sconosciuto'}\n**Data:** {w['timestamp'][:10]}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="clearwarns", description="Rimuove tutti i warn di un utente e le relative pene")
@app_commands.describe(member="Utente di cui azzerare i warn")
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    warns_data = load_json(WARNS_FILE)
    warns_data.setdefault(str(interaction.guild.id), {})[str(member.id)] = []
    save_json(WARNS_FILE, warns_data)

    # Rimuove anche il mute se presente
    config = load_json(CONFIG_FILE)
    muted_role_id = config.get(str(interaction.guild.id), {}).get("muted_role")
    muted_role = interaction.guild.get_role(muted_role_id) if muted_role_id else discord.utils.get(interaction.guild.roles, name="Muted")
    rimosso_mute = False
    if muted_role and muted_role in member.roles:
        await member.remove_roles(muted_role, reason="Warn azzerati — mute rimosso automaticamente")
        rimosso_mute = True

    descrizione = f"✅ Warn di {member.mention} azzerati."
    if rimosso_mute:
        descrizione += "
🔊 Mute rimosso automaticamente."

    await interaction.response.send_message(
        embed=discord.Embed(description=descrizione, color=discord.Color.green()),
        ephemeral=True
    )
    await send_log(interaction.guild, "WARN", interaction.user, member, reason="Warn azzerati" + (" + mute rimosso" if rimosso_mute else ""))

@tree.command(name="clear", description="Cancella messaggi dal canale (max 100)")
@app_commands.describe(quantita="Numero di messaggi")
async def clear(interaction: discord.Interaction, quantita: int):
    if not has_perm(interaction, "manage_messages"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    if quantita < 1 or quantita > 100:
        await interaction.response.send_message("❌ Inserisci un numero tra 1 e 100.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=quantita)
    await interaction.followup.send(
        embed=discord.Embed(description=f"🗑️ Cancellati **{len(deleted)}** messaggi.", color=discord.Color.blurple()),
        ephemeral=True
    )
    await send_log(interaction.guild, "CLEAR", interaction.user, interaction.channel,
                   extra={"📨 Messaggi": str(len(deleted)), "📌 Canale": interaction.channel.mention})

@tree.command(name="lock", description="Blocca il canale corrente")
@app_commands.describe(reason="Motivo")
async def lock(interaction: discord.Interaction, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_channels"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    channel = interaction.channel
    # Prende i permessi esistenti per @everyone senza sovrascriverli
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔒 Canale bloccato. Motivo: {reason}", color=discord.Color.dark_red())
    )
    await send_log(interaction.guild, "LOCK", interaction.user, channel,
                   reason=reason, extra={"📌 Canale": channel.mention})

@tree.command(name="unlock", description="Sblocca il canale corrente")
@app_commands.describe(reason="Motivo")
async def unlock(interaction: discord.Interaction, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_channels"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    channel = interaction.channel
    # Prende i permessi esistenti per @everyone senza sovrascriverli
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None  # Ripristina al default (eredita dai permessi del server)
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔓 Canale sbloccato. Motivo: {reason}", color=discord.Color.dark_green())
    )
    await send_log(interaction.guild, "UNLOCK", interaction.user, channel,
                   reason=reason, extra={"📌 Canale": channel.mention})

@tree.command(name="rimuoviruolo", description="Rimuove un ruolo a un utente")
@app_commands.describe(member="Utente", ruolo="Ruolo da rimuovere", reason="Motivo")
async def rimuoviruolo(interaction: discord.Interaction, member: discord.Member, ruolo: discord.Role, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_roles"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    if ruolo not in member.roles:
        await interaction.response.send_message(f"❌ {member.mention} non ha il ruolo {ruolo.mention}.", ephemeral=True)
        return
    await member.remove_roles(ruolo, reason=reason)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🎭 Ruolo {ruolo.mention} rimosso a {member.mention}.", color=discord.Color.purple()),
        ephemeral=True
    )
    await send_log(interaction.guild, "RIMUOVI RUOLO", interaction.user, member,
                   reason=reason, extra={"🎭 Ruolo": ruolo.name})

# ─────────────────────────────────────────
#  AVVIO BOT
# ─────────────────────────────────────────

# ─────────────────────────────────────────
#  /serverlock e /serverunlock (solo owner)
# ─────────────────────────────────────────
@tree.command(name="serverlock", description="Blocca TUTTI i canali del server (solo owner)")
@app_commands.describe(reason="Motivo del blocco")
async def serverlock(interaction: discord.Interaction, reason: str = "Nessun motivo specificato"):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Solo i possessori del bot possono usare questo comando.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    bloccati = 0
    for channel in interaction.guild.channels:
        try:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = False
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            bloccati += 1
        except Exception:
            pass
    await interaction.followup.send(
        embed=discord.Embed(
            description=f"🔒 Server bloccato! **{bloccati}** canali bloccati. Motivo: {reason}",
            color=discord.Color.dark_red()
        ),
        ephemeral=True
    )
    await send_log(interaction.guild, "LOCK", interaction.user, interaction.guild,
                   reason=f"[SERVER LOCK] {reason}",
                   extra={"🔒 Canali bloccati": str(bloccati)})

@tree.command(name="serverunlock", description="Sblocca TUTTI i canali del server (solo owner)")
@app_commands.describe(reason="Motivo dello sblocco")
async def serverunlock(interaction: discord.Interaction, reason: str = "Nessun motivo specificato"):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Solo i possessori del bot possono usare questo comando.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    sbloccati = 0
    for channel in interaction.guild.channels:
        try:
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = None
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            sbloccati += 1
        except Exception:
            pass
    await interaction.followup.send(
        embed=discord.Embed(
            description=f"🔓 Server sbloccato! **{sbloccati}** canali sbloccati. Motivo: {reason}",
            color=discord.Color.dark_green()
        ),
        ephemeral=True
    )
    await send_log(interaction.guild, "UNLOCK", interaction.user, interaction.guild,
                   reason=f"[SERVER UNLOCK] {reason}",
                   extra={"🔓 Canali sbloccati": str(sbloccati)})

# ─────────────────────────────────────────
#  /antispam_configura - mute automatico configurabile
# ─────────────────────────────────────────
@tree.command(name="antispam_configura", description="Configura il mute automatico per spam")
@app_commands.describe(
    messaggi="Numero di messaggi per scattare il mute automatico",
    secondi="Finestra di tempo in secondi",
    durata_mute="Durata del mute automatico (es. 5m, 1h) — vuoto = permanente"
)
async def antispam_configura(interaction: discord.Interaction, messaggi: int, secondi: int, durata_mute: str = None):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    if messaggi < 2 or messaggi > 50:
        await interaction.response.send_message("❌ Il numero di messaggi deve essere tra 2 e 50.", ephemeral=True)
        return
    if secondi < 2 or secondi > 60:
        await interaction.response.send_message("❌ La finestra di tempo deve essere tra 2 e 60 secondi.", ephemeral=True)
        return
    if durata_mute and parse_duration(durata_mute) is None:
        await interaction.response.send_message("❌ Formato durata non valido. Usa: 10s, 5m, 2h, 1d", ephemeral=True)
        return

    config = load_json(CONFIG_FILE)
    guild_id = str(interaction.guild.id)
    config.setdefault(guild_id, {}).setdefault("automod", {})["antispam"] = True
    config[guild_id]["automod"]["spam_limit"]  = messaggi
    config[guild_id]["automod"]["spam_window"] = secondi
    config[guild_id]["automod"]["spam_mute_duration"] = durata_mute
    save_json(CONFIG_FILE, config)

    durata_str = format_duration(parse_duration(durata_mute)) if durata_mute else "Permanente"
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🛡️ Antispam configurato",
            description=f"**Messaggi:** {messaggi} in {secondi} secondi
**Mute automatico:** {durata_str}",
            color=discord.Color.gold()
        ),
        ephemeral=True
    )

bot.run(TOKEN)
