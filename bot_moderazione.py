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
TOKEN    =
OWNER_ID = 1222812045184073750

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
    return interaction.user.id == OWNER_ID

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
            await channel.set_permissions(muted_role, send_messages=False, speak=False)
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
        spam_tracker[uid] = [t for t in spam_tracker[uid] if (now - t).total_seconds() < SPAM_WINDOW]
        spam_tracker[uid].append(now)
        if len(spam_tracker[uid]) >= SPAM_LIMIT:
            motivo = f"Spam rilevato ({SPAM_LIMIT} messaggi in {SPAM_WINDOW}s)"
            spam_tracker[uid] = []

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
#  VIEW CONFERMA BAN ALL
# ─────────────────────────────────────────
class BanAllView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.confermato = False

    @discord.ui.button(label="✅ Conferma BAN ALL", style=discord.ButtonStyle.danger)
    async def conferma(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Solo il possessore del bot può confermare.", ephemeral=True)
            return
        self.confermato = True
        self.stop()
        await interaction.response.send_message("☢️ Ban di massa in corso...", ephemeral=True)

        bannati = 0
        errori = 0
        async for member in interaction.guild.fetch_members():
            if member.bot or member.id == OWNER_ID:
                continue
            if member.guild_permissions.administrator:
                continue
            try:
                await member.ban(reason="[BAN ALL] Eseguito dal possessore del bot")
                bannati += 1
            except Exception:
                errori += 1

        await send_log(interaction.guild, "BAN ALL", interaction.user, interaction.guild,
                       reason="Ban di massa eseguito dal possessore",
                       extra={"✅ Bannati": str(bannati), "❌ Errori": str(errori)})

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"☢️ Ban di massa completato!\n✅ Bannati: **{bannati}**\n❌ Errori: **{errori}**",
                color=discord.Color.dark_red()
            ),
            ephemeral=True
        )

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

@tree.command(name="banall", description="⚠️ Banna tutti i membri non amministratori (solo owner)")
async def banall(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message("❌ Solo il possessore del bot può usare questo comando.", ephemeral=True)
        return
    embed = discord.Embed(
        title="☢️ CONFERMA BAN DI MASSA",
        description="Stai per **bannare TUTTI i membri** del server che non sono amministratori.\n\n"
                    "Questa azione è **irreversibile**. Sei sicuro?",
        color=discord.Color.dark_red()
    )
    await interaction.response.send_message(embed=embed, view=BanAllView(), ephemeral=True)

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

@tree.command(name="clearwarns", description="Rimuove tutti i warn di un utente")
@app_commands.describe(member="Utente di cui azzerare i warn")
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    if not has_perm(interaction, "administrator"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    warns_data = load_json(WARNS_FILE)
    warns_data.setdefault(str(interaction.guild.id), {})[str(member.id)] = []
    save_json(WARNS_FILE, warns_data)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"✅ Warn di {member.mention} azzerati.", color=discord.Color.green()),
        ephemeral=True
    )
    await send_log(interaction.guild, "WARN", interaction.user, member, reason="Warn azzerati da un amministratore")

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
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔒 Canale bloccato. Motivo: {reason}", color=discord.Color.dark_red())
    )
    await send_log(interaction.guild, "LOCK", interaction.user, interaction.channel,
                   reason=reason, extra={"📌 Canale": interaction.channel.mention})

@tree.command(name="unlock", description="Sblocca il canale corrente")
@app_commands.describe(reason="Motivo")
async def unlock(interaction: discord.Interaction, reason: str = "Nessun motivo specificato"):
    if not has_perm(interaction, "manage_channels"):
        await interaction.response.send_message("❌ Non hai i permessi.", ephemeral=True)
        return
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message(
        embed=discord.Embed(description=f"🔓 Canale sbloccato. Motivo: {reason}", color=discord.Color.dark_green())
    )
    await send_log(interaction.guild, "UNLOCK", interaction.user, interaction.channel,
                   reason=reason, extra={"📌 Canale": interaction.channel.mention})

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
bot.run(TOKEN)
