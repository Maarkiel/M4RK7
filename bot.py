import discord
from discord.ext import commands
from discord import app_commands
import os
import sqlite3
from dotenv import load_dotenv

# Wczytaj zmienne środowiskowe z pliku .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Nie znaleziono DISCORD_TOKEN w pliku .env!")

# Intencje
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Połączenie z bazą danych
conn = sqlite3.connect("user_data.db")
c = conn.cursor()

# Tabele w bazie
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    warns INTEGER DEFAULT 0
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action_type TEXT,
    reason TEXT,
    moderator TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# ----------------------
# EVENTY I KOMENDY
# ----------------------

@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako: {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"✅ Zsynchronizowano {len(synced)} komend slash.")
    except Exception as e:
        print(f"❌ Błąd synchronizacji komend: {e}")

@tree.command(name="kartoteka", description="Zarządzanie użytkownikiem")
@app_commands.describe(username="Użytkownik do przeglądu")
async def kartoteka(interaction: discord.Interaction, username: discord.Member):
    user_id = str(username.id)
    c.execute("SELECT warns FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    warns = result[0] if result else 0

    c.execute("SELECT COUNT(*) FROM actions WHERE user_id = ? AND action_type = 'mute'", (user_id,))
    mutes = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM actions WHERE user_id = ? AND action_type = 'ban'", (user_id,))
    bans = c.fetchone()[0]

    embed = discord.Embed(title="Kartoteka użytkownika", color=discord.Color.blue())
    embed.set_thumbnail(url=username.display_avatar.url)
    embed.add_field(name="Nazwa", value=username.name, inline=False)
    embed.add_field(name="ID", value=username.id, inline=False)
    embed.add_field(name="Warny", value=str(warns), inline=True)
    embed.add_field(name="Mute", value=str(mutes), inline=True)
    embed.add_field(name="Bany", value=str(bans), inline=True)

    view = KartotekaButtons(username)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class KartotekaButtons(discord.ui.View):
    def __init__(self, user: discord.Member):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Kartoteka", style=discord.ButtonStyle.primary)
    async def kartoteka_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        c.execute("SELECT action_type, reason, moderator, timestamp FROM actions WHERE user_id = ? ORDER BY timestamp DESC", (str(self.user.id),))
        records = c.fetchall()
        if not records:
            msg = "Brak historii."
        else:
            msg = "\n".join([f"[{r[3]}] {r[0].upper()} - {r[2]}: {r[1]}" for r in records])
        await interaction.response.send_message(f"Historia dla {self.user.mention}:\n```{msg}```", ephemeral=True)

    @discord.ui.button(label="Ostrzeż", style=discord.ButtonStyle.danger)
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = WarnModal(self.user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Zbanuj", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BanModal(self.user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Zamknij", style=discord.ButtonStyle.secondary)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

class WarnModal(discord.ui.Modal, title="Ostrzeż użytkownika"):
    reason = discord.ui.TextInput(label="Powód ostrzeżenia", style=discord.TextStyle.paragraph)

    def __init__(self, user: discord.Member):
        super().__init__()
        self.user = user

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(self.user.id)
        c.execute("SELECT warns FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        warns = row[0] + 1 if row else 1

        c.execute("INSERT OR REPLACE INTO users (user_id, warns) VALUES (?, ?)", (user_id, warns))
        c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                  (user_id, "warn", self.reason.value, str(interaction.user)))
        conn.commit()

        await interaction.response.send_message(f"{self.user.mention} został ostrzeżony. Powód: {self.reason.value}", ephemeral=True)

        if warns in [2, 5]:
            try:
                await interaction.guild.timeout(self.user, duration=60*60*24*3, reason="Automatyczny mute za ostrzeżenia")
            except Exception as e:
                print(f"Błąd podczas mutowania: {e}")
            c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                      (user_id, "mute", "Automatyczny mute za ostrzeżenia", str(interaction.user)))
        elif warns in [3, 6]:
            try:
                await interaction.guild.ban(self.user, reason="Automatyczny ban za ostrzeżenia")
            except Exception as e:
                print(f"Błąd podczas bana: {e}")
            c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                      (user_id, "ban", "Automatyczny ban za ostrzeżenia", str(interaction.user)))
        conn.commit()

class BanModal(discord.ui.Modal, title="Zbanuj użytkownika"):
    reason = discord.ui.TextInput(label="Powód bana", style=discord.TextStyle.paragraph)

    def __init__(self, user: discord.Member):
        super().__init__()
        self.user = user

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.user.send(f"Zostałeś zbanowany przez {interaction.user.mention}. Powód: {self.reason.value}")
        except Exception:
            pass

        try:
            await interaction.guild.ban(self.user, reason=self.reason.value)
        except Exception as e:
            print(f"Błąd podczas bana: {e}")

        user_id = str(self.user.id)
        c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                  (user_id, "ban", self.reason.value, str(interaction.user)))
        conn.commit()

        await interaction.response.send_message(f"{self.user.mention} został zbanowany.", ephemeral=True)

@tree.command(name="warn", description="Ostrzeż użytkownika")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    user_id = str(user.id)
    c.execute("SELECT warns FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    warns = row[0] + 1 if row else 1

    c.execute("INSERT OR REPLACE INTO users (user_id, warns) VALUES (?, ?)", (user_id, warns))
    c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
              (user_id, "warn", reason, str(interaction.user)))
    conn.commit()

    await interaction.response.send_message(f"{user.mention} otrzymał ostrzeżenie: {reason}", ephemeral=True)

    if warns in [2, 5]:
        try:
            await interaction.guild.timeout(user, duration=60*60*24*3, reason="Automatyczny mute za ostrzeżenia")
        except Exception as e:
            print(f"Błąd podczas mutowania: {e}")
        c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                  (user_id, "mute", "Automatyczny mute", str(interaction.user)))
    elif warns in [3, 6]:
        try:
            await interaction.guild.ban(user, reason="Automatyczny ban za ostrzeżenia")
        except Exception as e:
            print(f"Błąd podczas bana: {e}")
        c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
                  (user_id, "ban", "Automatyczny ban", str(interaction.user)))
    conn.commit()

@tree.command(name="ban", description="Banuje użytkownika")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str):
    try:
        await user.send(f"Zostałeś zbanowany przez {interaction.user.mention}. Powód: {reason}")
    except Exception:
        pass
    try:
        await interaction.guild.ban(user, reason=reason)
    except Exception as e:
        print(f"Błąd podczas bana: {e}")
    c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
              (str(user.id), "ban", reason, str(interaction.user)))
    conn.commit()
    await interaction.response.send_message(f"{user.mention} został zbanowany.", ephemeral=True)

@tree.command(name="mute", description="Wycisza użytkownika")
async def mute(interaction: discord.Interaction, user: discord.Member, time: str):
    try:
        await interaction.guild.timeout(user, duration=60*60*24*3, reason=f"Mute komendą ({time})")
    except Exception as e:
        print(f"Błąd podczas mutowania: {e}")
    c.execute("INSERT INTO actions (user_id, action_type, reason, moderator) VALUES (?, ?, ?, ?)",
              (str(user.id), "mute", f"Wyciszenie na 3 dni ({time})", str(interaction.user)))
    conn.commit()
    await interaction.response.send_message(f"{user.mention} został wyciszony na 3 dni.", ephemeral=True)

# Uruchomienie bota
bot.run(TOKEN)
print(f"Token from env: {TOKEN[:10]}...")  # Wyświetli pierwsze 10 znaków tokena

