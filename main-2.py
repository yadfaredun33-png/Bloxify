import discord
from discord.ext import commands
import json
import os
import random
import asyncio
import shutil
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ.get("DISCORD_TOKEN")
INVITE_CHANNEL_ID = 1504917763485990934

intents = discord.Intents.default()
intents.members = True
intents.invites = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

invite_cache = {}
auto_roll_tasks = {}

# ── Fruit config ─────────────────────────────────────────────────────────────

FRUITS = ["Kitsune", "Buddha", "Yeti", "Venom", "Gravity", "Storage", "Gas", "Dough"]

FRUIT_EMOJIS = {
    "Kitsune": "🦊",
    "Buddha":  "☮️",
    "Yeti":    "❄️",
    "Venom":   "🕷️",
    "Gravity": "🌀",
    "Storage": "📦",
    "Gas":     "💨",
    "Dough":   "🍞",
}

# ── File loaders ─────────────────────────────────────────────────────────────

def load_messages():
    """Load messages from messages.json, merging default + custom lists."""
    try:
        with open("messages.json", "r") as f:
            data = json.load(f)
        pool = data.get("default", []) + data.get("custom", [])
        # Strip out the instruction placeholder strings (no {fruit} = skip)
        pool = [m for m in pool if "{fruit}" in m]
        return pool if pool else ["{fruit} fruit just dropped!"]
    except (FileNotFoundError, json.JSONDecodeError):
        return ["{fruit} fruit just dropped!"]


def load_invite_counts():
    try:
        with open("invite_counts.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_invite_counts(counts):
    """Atomic write — temp file then replace, so a crash mid-write never corrupts data."""
    tmp = "invite_counts.tmp"
    with open(tmp, "w") as f:
        json.dump(counts, f, indent=2)
    shutil.move(tmp, "invite_counts.json")


def load_stock():
    try:
        with open("stock.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# ── Embed builder ─────────────────────────────────────────────────────────────

def random_stars():
    return "⭐" * random.choices([3, 4, 5], weights=[1, 2, 4])[0]


def build_roll_embed(message, fruit=None):
    stars = random_stars()
    emoji = FRUIT_EMOJIS.get(fruit, "🎲") if fruit else "🎲"
    embed = discord.Embed(
        description=f"## {stars}\n> {message}",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    if fruit:
        embed.set_footer(text=f"{emoji} {fruit} Fruit")
    return embed

# ── Invite caching ────────────────────────────────────────────────────────────

async def cache_invites(guild):
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {inv.code: inv for inv in invites}
        print(f"Cached {len(invite_cache[guild.id])} invite(s) for {guild.name}")
    except Exception as e:
        print(f"Could not cache invites for {guild.name}: {e}")
        invite_cache[guild.id] = {}

# ── Bot events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    for guild in bot.guilds:
        await cache_invites(guild)
    print(f"Online as {bot.user} | {len(bot.guilds)} guild(s)")


@bot.event
async def on_guild_join(guild):
    await cache_invites(guild)


@bot.event
async def on_invite_create(invite):
    invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite


@bot.event
async def on_invite_delete(invite):
    invite_cache.get(invite.guild.id, {}).pop(invite.code, None)


@bot.event
async def on_member_join(member):
    guild = member.guild

    try:
        new_invites = {inv.code: inv for inv in await guild.invites()}
    except Exception as e:
        print(f"Failed to fetch invites on join ({guild.name}): {e}")
        return

    cached = invite_cache.get(guild.id, {})
    inviter = None

    # Normal invite — use count went up
    for code, invite in new_invites.items():
        old = cached.get(code)
        if old and invite.uses > old.uses:
            inviter = invite.inviter
            break

    # Single-use invite — it disappeared after use
    if not inviter:
        for code, old_invite in cached.items():
            if code not in new_invites and old_invite.max_uses == 1:
                inviter = old_invite.inviter
                break

    # Update cache AFTER finding the inviter
    invite_cache[guild.id] = new_invites

    if not inviter:
        print(f"Could not find inviter for {member} — invite may have been created before bot started")
        return

    # Load, increment, and atomically save invite counts
    counts = load_invite_counts()
    uid = str(inviter.id)
    counts[uid] = counts.get(uid, 0) + 1
    save_invite_counts(counts)

    channel = bot.get_channel(INVITE_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            description=(
                f"👋 {member.mention} has been invited by {inviter.mention}\n"
                f"**{inviter.display_name}** now has **{counts[uid]}** invite(s)"
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Invite Tracker")
        await channel.send(embed=embed)

# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name="reset")
@commands.has_permissions(administrator=True)
async def reset_invites(ctx, user: discord.Member):
    counts = load_invite_counts()
    counts[str(user.id)] = 0
    save_invite_counts(counts)
    embed = discord.Embed(
        description=f"🔄 {user.mention}'s invites have been reset to **0**.",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Reset by {ctx.author.display_name}")
    await ctx.send(embed=embed)


@reset_invites.error
async def reset_invites_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(description="❌ You don't have permission to use this.", color=discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(description="❌ Usage: `!reset @user`", color=discord.Color.red()))


@bot.command(name="stock")
async def stock(ctx):
    stock_data = load_stock()
    if not stock_data:
        await ctx.send(embed=discord.Embed(description="❌ No stock data found.", color=discord.Color.red()))
        return

    lines = "\n".join(
        f"{FRUIT_EMOJIS.get(item, '🎲')} **{item}** — `{amount}`"
        for item, amount in stock_data.items()
    )
    embed = discord.Embed(
        title="🏪 Current Stock",
        description=lines,
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="Stock • Last updated")
    await ctx.send(embed=embed)


@bot.command(name="start")
@commands.has_permissions(administrator=True)
async def start_roll(ctx):
    guild_id = ctx.guild.id

    if guild_id in auto_roll_tasks and not auto_roll_tasks[guild_id].done():
        await ctx.send(embed=discord.Embed(
            description="⚠️ Auto-roll is already running. Use `!stop` to stop it first.",
            color=discord.Color.red()
        ))
        return

    await ctx.send(embed=discord.Embed(
        description="✅ Auto-roll started — posting every **1–3 minutes**.\nUse `!stop` to stop.",
        color=discord.Color.red()
    ))

    async def roll_loop():
        while True:
            await asyncio.sleep(random.randint(60, 180))
            fruit = random.choice(FRUITS)
            # Reload messages every loop so edits to messages.json apply instantly
            messages = load_messages()
            template = random.choice(messages)
            text = template.format(fruit=fruit)
            await ctx.channel.send(embed=build_roll_embed(text, fruit))

    auto_roll_tasks[guild_id] = asyncio.create_task(roll_loop())


@start_roll.error
async def start_roll_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(description="❌ You need administrator permission.", color=discord.Color.red()))


@bot.command(name="stop")
@commands.has_permissions(administrator=True)
async def stop_roll(ctx):
    guild_id = ctx.guild.id
    task = auto_roll_tasks.get(guild_id)

    if task and not task.done():
        task.cancel()
        del auto_roll_tasks[guild_id]
        await ctx.send(embed=discord.Embed(description="🛑 Auto-roll stopped.", color=discord.Color.red()))
    else:
        await ctx.send(embed=discord.Embed(description="⚠️ Auto-roll isn't running.", color=discord.Color.red()))


@bot.command(name="link")
async def link(ctx):
    embed = discord.Embed(
        title="🍎 Claim Your Fruits — BloxHub",
        description=(
            "Welcome to **BloxHub**, the only place where fruits are given away — never taken.\n"
            "We will **never** ask you to hand over your fruits. Everything here is free.\n\n"
            "**How it works:**\n"
            "› Visit our website using the button below\n"
            "› Browse the available fruits and click the one you want\n"
            "› Follow the on-screen steps to join the bot's in-game session\n"
            "› Receive your fruit — simple as that\n\n"
            "**Having trouble?**\n"
            "*(If there is no one in the game when you join, please DM the owners so we can get the bot back online for you)*"
        ),
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="BloxHub • Free Fruit Giveaways")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Go to BloxHub",
        url="https://bloxhub-gamma.vercel.app/",
        style=discord.ButtonStyle.link,
        emoji="🍎"
    ))
    await ctx.send(embed=embed, view=view)


@bot.command(name="flex")
async def flex(ctx, *, message: str):
    await ctx.send(embed=build_roll_embed(message))


@flex.error
async def flex_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(
            description="❌ Usage: `!flex your message here`\nExample: `!flex yooo I just got Buddha fr fr`",
            color=discord.Color.red()
        ))


bot.run(TOKEN)
