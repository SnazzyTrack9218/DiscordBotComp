import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import time
import logging
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

# Command restriction
COMMANDS_CHANNEL = "commands"

@bot.check
async def restrict_commands_channel(ctx):
    if ctx.channel.name != COMMANDS_CHANNEL:
        await ctx.send(embed=discord.Embed(title="❌ Wrong Channel", description=f"Use #{COMMANDS_CHANNEL}!", color=discord.Color.red()))
        return False
    return True

# SQLite database setup
def init_db():
    try:
        conn = sqlite3.connect('siege_hub.db')
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            currency INTEGER DEFAULT 1000,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            format TEXT,
            team1 TEXT,
            team2 TEXT,
            winner TEXT,
            points INTEGER,
            status TEXT,
            timestamp TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS daily_claims (
            user_id INTEGER PRIMARY KEY,
            last_claim TEXT
        )''')
        conn.commit()
        return conn, cursor
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        return None, None

conn, cursor = init_db()

# Bot variables
MATCH_FORMATS = ['1v1', '2v2', '3v3', '4v4', '5v5']
THUMBNAIL_URL = os.getenv("THUMBNAIL_URL", "https://www.pngall.com/wp-content/uploads/5/Rainbow-Six-Siege-Logo-PNG-Free-Download.png")
MATCH_COOLDOWN = 300  # 5 minutes
DAILY_CURRENCY = 100
DAILY_COOLDOWN = 24 * 60 * 60  # 24 hours
MATCH_WIN_CURRENCY = 100
current_match = None
votes = {}
format_votes = {}
cooldowns = defaultdict(lambda: 0)
active_teams = {}

# Helper functions
def get_footer_text():
    return "Siege Competitive Hub"

async def log_error_to_channel(guild, message):
    try:
        channel = discord.utils.get(guild.text_channels, name='bot-logs')
        if channel:
            embed = discord.Embed(title="❌ Bot Error", description=message, color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
            embed.set_footer(text=get_footer_text())
            await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Failed to send error to bot-logs: {e}")

def get_user(user_id):
    try:
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            update_user(user_id)
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        return user
    except sqlite3.Error as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None

def update_user(user_id, points=0, currency=1000, wins=0, losses=0, banned=0):
    try:
        cursor.execute('INSERT OR REPLACE INTO users (user_id, points, currency, wins, losses, banned) VALUES (?, ?, ?, ?, ?, ?)',
                      (user_id, points, currency, wins, losses, banned))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating user {user_id}: {e}")

def deduct_currency(user_id, amount):
    user = get_user(user_id)
    if not user or user[2] < amount:
        return False
    update_user(user_id, user[1], user[2] - amount, user[3], user[4], user[5])
    return True

async def assign_rank_role(member, points):
    try:
        rank = "Gold" if points > 1000 else "Silver" if points > 500 else "Bronze"
        role_name = f"Rank_{rank}"
        role = discord.utils.get(member.guild.roles, name=role_name)
        if not role:
            color = discord.Color.gold() if rank == "Gold" else discord.Color.greyple() if rank == "Silver" else discord.Color.dark_orange()
            role = await member.guild.create_role(name=role_name, color=color)
        for r in member.roles:
            if r.name.startswith("Rank_") and r.name != role_name:
                await member.remove_roles(r)
        if role not in member.roles:
            await member.add_roles(role)
    except discord.errors.Forbidden:
        logger.warning(f"Missing permissions to assign role to {member.name}")
    except Exception as e:
        logger.error(f"Error assigning rank to {member.name}: {e}")
        await log_error_to_channel(member.guild, f"Error assigning rank to {member.name}: {e}")

# Bot events
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    save_data.start()

@tasks.loop(minutes=5)
async def save_data():
    try:
        conn.commit()
        logger.debug("Database saved")
    except sqlite3.Error as e:
        logger.error(f"Error saving database: {e}")

# Commands
@bot.command()
async def help(ctx):
    try:
        embed = discord.Embed(title="🎮 Siege Competitive Hub Commands", description="Simplified R6 bot!", color=discord.Color.purple())
        commands_list = [
            ("🎯 !start_match", "Start a skill-based match"),
            ("🏁 !matchend", "End match and vote for winner"),
            ("📜 !match_history [user]", "View match history"),
            ("👤 !profile [user]", "View user profile"),
            ("📊 !leaderboard", "Top 10 players"),
            ("💰 !balance", "Check currency"),
            ("🎁 !daily", "Claim daily reward"),
            ("⚖️ !dispute <match_id>", "Report match issue"),
            ("🔧 !add_currency <user> <amount>", "Admin: Add currency"),
            ("📈 !adjust_points <user> <amount>", "Admin: Adjust points"),
            ("🚫 !ban_from_matchmaking <user>", "Admin: Ban/unban"),
            ("🛑 !clear_match", "Admin: Clear active match")
        ]
        for name, value in commands_list:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !help: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !help: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to display help.", color=discord.Color.red()))

@bot.command()
async def start_match(ctx):
    try:
        global current_match, votes, format_votes
        if current_match:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="Match in progress!", color=discord.Color.red()))
        
        user_id = ctx.author.id
        user = get_user(user_id)
        if not user:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        if user[5]:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="You are banned!", color=discord.Color.red()))
        
        if cooldowns[user_id] > time.time():
            return await ctx.send(embed=discord.Embed(title="❌ Error", description=f"Wait {int(cooldowns[user_id] - time.time())} seconds!", color=discord.Color.red()))
        
        # Ensure teams exist
        team1_name = "Team 1"
        team2_name = "Team 2"
        if team1_name not in active_teams:
            active_teams[team1_name] = {'leader': None, 'members': [], 'points': 0}
        if team2_name not in active_teams:
            active_teams[team2_name] = {'leader': None, 'members': [], 'points': 0}
        
        # Get voice channel members
        team1_channel = discord.utils.get(ctx.guild.voice_channels, name="Team 1")
        team2_channel = discord.utils.get(ctx.guild.voice_channels, name="Team 2")
        team1_members = team1_channel.members if team1_channel else []
        team2_members = team2_channel.members if team2_channel else []
        
        # Add voice channel members to teams
        for member in team1_members:
            if member not in active_teams[team1_name]['members']:
                active_teams[team1_name]['members'].append(member)
                if not active_teams[team1_name]['leader']:
                    active_teams[team1_name]['leader'] = member
        for member in team2_members:
            if member not in active_teams[team2_name]['members']:
                active_teams[team2_name]['members'].append(member)
                if not active_teams[team2_name]['leader']:
                    active_teams[team2_name]['leader'] = member
        
        # Vote for match format
        format_votes.clear()
        embed = discord.Embed(title="⚔️ Vote Match Format", description="React to choose format!", color=discord.Color.purple())
        for i, fmt in enumerate(MATCH_FORMATS):
            embed.add_field(name=f"**{fmt}**", value=f"React with {i+1}️⃣", inline=True)
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text="Voting ends in 30s")
        msg = await ctx.send(embed=embed)
        for i in range(len(MATCH_FORMATS)):
            await msg.add_reaction(f"{i+1}️⃣")
        
        await asyncio.sleep(30)
        chosen_format = max(format_votes, key=format_votes.get, default='1v1')
        team_size = int(chosen_format[0])
        
        # Announce currency reward
        embed = discord.Embed(
            title="💰 Match Reward",
            description=f"Winning team gains {MATCH_WIN_CURRENCY} currency per player! Join a team using buttons.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text="Join teams within 30s")
        view = TeamJoinView(team1_name, team2_name)
        await ctx.send(embed=embed, view=view)
        
        # Wait for button interactions
        await asyncio.sleep(30)
        view.stop()
        
        # Check team sizes
        team1_count = len(active_teams[team1_name]['members'])
        team2_count = len(active_teams[team2_name]['members'])
        if chosen_format == '1v1' and team1_count == 0 and team2_count == 0:
            return await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description="Need at least 1 player for 1v1!",
                color=discord.Color.red()
            ))
        elif chosen_format != '1v1' and (team1_count < team_size or team2_count < team_size):
            return await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"Need {team_size} player{'s' if team_size > 1 else ''} per team! Got {team1_count} in Team 1, {team2_count} in Team 2.",
                color=discord.Color.red()
            ))
        
        team1_members = active_teams[team1_name]['members'][:team_size]
        team2_members = active_teams[team2_name]['members'][:team_size]
        team1_names = ', '.join(m.name for m in team1_members) if team1_members else "None"
        team2_names = ', '.join(m.name for m in team2_members) if team2_members else "None"
        
        # Update team points
        active_teams[team1_name]['points'] = sum(get_user(m.id)[1] for m in team1_members) / len(team1_members) if team1_members else 0
        active_teams[team2_name]['points'] = sum(get_user(m.id)[1] for m in team2_members) / len(team2_members) if team2_members else 0
        
        # Start match
        cursor.execute('INSERT INTO matches (format, team1, team2, status, timestamp) VALUES (?, ?, ?, ?, ?)',
                      (chosen_format, team1_names, team2_names, 'active', datetime.now().isoformat()))
        conn.commit()
        current_match = cursor.lastrowid
        
        embed = discord.Embed(
            title="⚔️ Match Started",
            description=f"**Format**: {chosen_format}\n**Team 1**: {team1_names}\n**Team 2**: {team2_names}\n**Reward**: {MATCH_WIN_CURRENCY} currency per winner",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        for member in team1_members + team2_members:
            try:
                await member.send(embed=embed)
            except:
                logger.warning(f"Failed to DM {member.name}")
        await ctx.send(embed=embed)
        
        for member in team1_members + team2_members:
            cooldowns[member.id] = time.time() + MATCH_COOLDOWN
    except Exception as e:
        logger.error(f"Error in !start_match: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !start_match: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to start match.", color=discord.Color.red()))

class TeamJoinView(discord.ui.View):
    def __init__(self, team1_name, team2_name):
        super().__init__(timeout=30)
        self.team1_name = team1_name
        self.team2_name = team2_name
    
    @discord.ui.button(label="Join Team 1", style=discord.ButtonStyle.primary, emoji="1️⃣")
    async def join_team1(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        for team_name in [self.team1_name, self.team2_name]:
            if user in active_teams[team_name]['members']:
                active_teams[team_name]['members'].remove(user)
                if active_teams[team_name]['leader'] == user and active_teams[team_name]['members']:
                    active_teams[team_name]['leader'] = active_teams[team_name]['members'][0]
                elif active_teams[team_name]['leader'] == user:
                    active_teams[team_name]['leader'] = None
        if user not in active_teams[self.team1_name]['members']:
            active_teams[self.team1_name]['members'].append(user)
            if not active_teams[self.team1_name]['leader']:
                active_teams[self.team1_name]['leader'] = user
        await interaction.response.send_message(f"{user.mention} joined Team 1!", ephemeral=True)
    
    @discord.ui.button(label="Join Team 2", style=discord.ButtonStyle.primary, emoji="2️⃣")
    async def join_team2(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        for team_name in [self.team1_name, self.team2_name]:
            if user in active_teams[team_name]['members']:
                active_teams[team_name]['members'].remove(user)
                if active_teams[team_name]['leader'] == user and active_teams[team_name]['members']:
                    active_teams[team_name]['leader'] = active_teams[team_name]['members'][0]
                elif active_teams[team_name]['leader'] == user:
                    active_teams[team_name]['leader'] = None
        if user not in active_teams[self.team2_name]['members']:
            active_teams[self.team2_name]['members'].append(user)
            if not active_teams[self.team2_name]['leader']:
                active_teams[self.team2_name]['leader'] = user
        await interaction.response.send_message(f"{user.mention} joined Team 2!", ephemeral=True)

@bot.command()
async def matchend(ctx):
    try:
        global current_match, votes
        if not current_match:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="No active match!", color=discord.Color.red()))
        
        cursor.execute('SELECT team1, team2, format FROM matches WHERE match_id = ?', (current_match,))
        match = cursor.fetchone()
        if not match:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="Match not found!", color=discord.Color.red()))
        team1, team2, match_format = match

        # Define team names for cleanup
        team1_name = "Team 1"
        team2_name = "Team 2"
        
        votes.clear()
        embed = discord.Embed(title="🏆 Vote Winner", description="Who won? React to choose!", color=discord.Color.purple())
        embed.add_field(name="Team 1", value=team1, inline=True)
        embed.add_field(name="Team 2", value=team2, inline=True)
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text="Voting ends in 30s")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")
        
        await asyncio.sleep(30)
        team1_votes = votes.get('team1', 0)
        team2_votes = votes.get('team2', 0)
        
        if team1_votes == team2_votes:
            cursor.execute('UPDATE matches SET status = ?, winner = ?, points = ? WHERE match_id = ?', ('completed', 'Tie', 0, current_match))
            conn.commit()
            for team in [team1_name, team2_name]:
                if team in active_teams:
                    del active_teams[team]
            current_match = None
            return await ctx.send(embed=discord.Embed(title="🤝 Tie", description="No points awarded!", color=discord.Color.orange()))
        
        winner = 'Team 1' if team1_votes > team2_votes else 'Team 2'
        points = 100 if match_format == '5v5' else 50
        winner_team = team1 if winner == 'Team 1' else team2
        loser_team = team2 if winner == 'Team 1' else team1
        
        for member in ctx.channel.members:
            if member.name in winner_team:
                user = get_user(member.id)
                if user:
                    update_user(member.id, user[1] + points, user[2] + MATCH_WIN_CURRENCY, user[3] + 1, user[4], user[5])
                    await assign_rank_role(member, user[1] + points)
            elif member.name in loser_team:
                user = get_user(member.id)
                if user:
                    update_user(member.id, user[1], user[2], user[3], user[4] + 1, user[5])
        
        cursor.execute('UPDATE matches SET status = ?, winner = ?, points = ? WHERE match_id = ?', ('completed', winner, points, current_match))
        conn.commit()
        
        log_channel = discord.utils.get(ctx.guild.text_channels, name='match-logs') or ctx.channel
        embed = discord.Embed(
            title="📜 Match Log",
            description=f"Match #{current_match}\n**Format**: {match_format}\n**Team 1**: {team1}\n**Team 2**: {team2}\n**Winner**: {winner}\n**Points**: {points}\n**Currency**: {MATCH_WIN_CURRENCY} per winner",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await log_channel.send(embed=embed)
        
        embed = discord.Embed(title="🏆 Match Result", description=f"**{winner}** wins! Awarded {points} points and {MATCH_WIN_CURRENCY} currency.", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
        
        for team in [team1_name, team2_name]:
            if team in active_teams:
                del active_teams[team]
        current_match = None
    except Exception as e:
        logger.error(f"Error in !matchend: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !matchend: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to end match.", color=discord.Color.red()))

@bot.command()
async def match_history(ctx, user: discord.Member = None):
    try:
        user_id = user.id if user else None
        query = 'SELECT match_id, format, team1, team2, winner, points, timestamp FROM matches WHERE status = ?'
        params = ['completed']
        if user_id:
            query += ' AND (team1 LIKE ? OR team2 LIKE ?)'
            params.extend([f'%{user.name}%', f'%{user.name}%'])
        
        cursor.execute(query, params)
        matches = cursor.fetchall()
        embed = discord.Embed(title="📜 Match History", description=f"{'User' if user else 'Global'} history", color=discord.Color.purple())
        if not matches:
            embed.add_field(name="Empty", value="No matches found!", inline=False)
        for match in matches[:10]:
            embed.add_field(
                name=f"Match #{match[0]} ({match[6][:10]})",
                value=f"**Format**: {match[1]}\n**Team 1**: {match[2]}\n**Team 2**: {match[3]}\n**Winner**: {match[4]}\n**Points**: {match[5]}",
                inline=False
            )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !match_history: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !match_history: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to fetch match history.", color=discord.Color.red()))

@bot.command()
async def profile(ctx, user: discord.Member = None):
    try:
        target = user or ctx.author
        user_data = get_user(target.id)
        if not user_data:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        team = next((name for name, data in active_teams.items() if target in data['members']), 'None')
        rank = "Gold" if user_data[1] > 1000 else "Silver" if user_data[1] > 500 else "Bronze"
        embed = discord.Embed(title=f"👤 {target.name}'s Profile", color=discord.Color.purple())
        embed.add_field(name="Rank", value=rank, inline=True)
        embed.add_field(name="Points", value=user_data[1], inline=True)
        embed.add_field(name="Wins/Losses", value=f"{user_data[3]}/{user_data[4]}", inline=True)
        embed.add_field(name="Currency", value=user_data[2], inline=True)
        embed.add_field(name="Team", value=team, inline=True)
        embed.set_thumbnail(url=target.avatar.url if target.avatar else THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !profile: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !profile: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to display profile.", color=discord.Color.red()))

@bot.command()
async def leaderboard(ctx):
    try:
        cursor.execute('SELECT user_id, points FROM users ORDER BY points DESC LIMIT 10')
        leaders = cursor.fetchall()
        embed = discord.Embed(title="📊 Leaderboard", description="Top players!", color=discord.Color.purple())
        if not leaders:
            embed.add_field(name="Empty", value="No players yet!", inline=False)
        for i, (user_id, points) in enumerate(leaders, 1):
            user = await bot.fetch_user(user_id)
            rank = "Gold" if points > 1000 else "Silver" if points > 500 else "Bronze"
            embed.add_field(name=f"**{i}. {user.name}**", value=f"{points} points ({rank})", inline=False)
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !leaderboard: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !leaderboard: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to display leaderboard.", color=discord.Color.red()))

@bot.command()
async def balance(ctx):
    try:
        user = get_user(ctx.author.id)
        if not user:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        embed = discord.Embed(title="💰 Balance", description=f"Balance: **{user[2]}** currency", color=discord.Color.gold())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !balance: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !balance: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to check balance.", color=discord.Color.red()))

@bot.command()
async def daily(ctx):
    try:
        user_id = ctx.author.id
        user = get_user(user_id)
        if not user:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        cursor.execute('SELECT last_claim FROM daily_claims WHERE user_id = ?', (user_id,))
        last_claim = cursor.fetchone()
        
        current_time = datetime.now(timezone.utc)
        if last_claim:
            last_claim_time = datetime.fromisoformat(last_claim[0])
            if (current_time - last_claim_time).total_seconds() < DAILY_COOLDOWN:
                remaining = DAILY_COOLDOWN - (current_time - last_claim_time).total_seconds()
                hours, remainder = divmod(int(remaining), 3600)
                minutes, _ = divmod(remainder, 60)
                return await ctx.send(embed=discord.Embed(
                    title="❌ Cooldown",
                    description=f"Wait {hours}h {minutes}m for next claim!",
                    color=discord.Color.red()
                ))
        
        update_user(user_id, user[1], user[2] + DAILY_CURRENCY, user[3], user[4], user[5])
        cursor.execute('INSERT OR REPLACE INTO daily_claims (user_id, last_claim) VALUES (?, ?)',
                      (user_id, current_time.isoformat()))
        conn.commit()
        
        embed = discord.Embed(title="🎁 Daily Reward", description=f"Claimed {DAILY_CURRENCY} currency!", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !daily: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !daily: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to claim daily reward.", color=discord.Color.red()))

@bot.command()
async def dispute(ctx, match_id: int):
    try:
        cursor.execute('SELECT * FROM matches WHERE match_id = ?', (match_id,))
        match = cursor.fetchone()
        if not match:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="Match not found!", color=discord.Color.red()))
        
        channel = discord.utils.get(ctx.guild.text_channels, name='match-logs') or ctx.channel
        embed = discord.Embed(
            title="⚖️ Dispute Filed",
            description=f"Dispute for Match #{match_id} by {ctx.author.mention}. Admins will review.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Match Details", value=f"Format: {match[1]}\nTeam 1: {match[2]}\nTeam 2: {match[3]}\nWinner: {match[4]}", inline=False)
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await channel.send(embed=embed)
        await ctx.send(embed=discord.Embed(title="✅ Dispute Submitted", description=f"Dispute for Match #{match_id} filed.", color=discord.Color.green()))
    except Exception as e:
        logger.error(f"Error in !dispute: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !dispute: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to file dispute.", color=discord.Color.red()))

@bot.command()
@commands.has_permissions(administrator=True)
async def add_currency(ctx, user: discord.Member, amount: int):
    try:
        if amount <= 0:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="Amount must be positive!", color=discord.Color.red()))
        
        user_data = get_user(user.id)
        if not user_data:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        update_user(user.id, user_data[1], user_data[2] + amount, user_data[3], user_data[4], user_data[5])
        embed = discord.Embed(title="💰 Currency Added", description=f"Added {amount} currency to {user.name}.", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !add_currency: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !add_currency: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to add currency.", color=discord.Color.red()))

@bot.command()
@commands.has_permissions(administrator=True)
async def adjust_points(ctx, user: discord.Member, amount: int):
    try:
        user_data = get_user(user.id)
        if not user_data:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        new_points = max(0, user_data[1] + amount)
        update_user(user.id, new_points, user_data[2], user_data[3], user_data[4], user_data[5])
        await assign_rank_role(user, new_points)
        embed = discord.Embed(title="📈 Points Adjusted", description=f"Adjusted {user.name}'s points by {amount}. New: {new_points}.", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !adjust_points: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !adjust_points: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to adjust points.", color=discord.Color.red()))

@bot.command()
@commands.has_permissions(administrator=True)
async def ban_from_matchmaking(ctx, user: discord.Member):
    try:
        user_data = get_user(user.id)
        if not user_data:
            update_user(user.id, banned=1)
            user_data = get_user(user.id)
            if not user_data:
                return await ctx.send(embed=discord.Embed(title="❌ Error", description="User data error.", color=discord.Color.red()))
        
        new_ban_status = 1 if user_data[5] == 0 else 0
        update_user(user.id, user_data[1], user_data[2], user_data[3], user_data[4], new_ban_status)
        action = "banned" if new_ban_status else "unbanned"
        embed = discord.Embed(title="🚫 Matchmaking Ban", description=f"{user.name} {action} from matchmaking.", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !ban_from_matchmaking: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !ban_from_matchmaking: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to update ban status.", color=discord.Color.red()))

@bot.command()
@commands.has_permissions(administrator=True)
async def clear_match(ctx):
    try:
        global current_match
        if not current_match:
            return await ctx.send(embed=discord.Embed(title="❌ Error", description="No active match!", color=discord.Color.red()))
        
        cursor.execute('UPDATE matches SET status = ? WHERE match_id = ?', ('cancelled', current_match))
        conn.commit()
        for team in ["Team 1", "Team 2"]:
            if team in active_teams:
                del active_teams[team]
        current_match = None
        embed = discord.Embed(title="🛑 Match Cleared", description="Active match cleared.", color=discord.Color.green())
        embed.set_thumbnail(url=THUMBNAIL_URL)
        embed.set_footer(text=get_footer_text())
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in !clear_match: {e}")
        await log_error_to_channel(ctx.guild, f"Error in !clear_match: {e}")
        await ctx.send(embed=discord.Embed(title="❌ Error", description="Failed to clear match.", color=discord.Color.red()))

@bot.event
async def on_reaction_add(reaction, user):
    global format_votes, votes
    if user.bot or not reaction.message.author.bot:
        return
    
    try:
        embed_title = reaction.message.embeds[0].title if reaction.message.embeds else ""
        emoji = str(reaction.emoji)
        
        if "Vote Match Format" in embed_title:
            if emoji in [f"{i+1}️⃣" for i in range(len(MATCH_FORMATS))]:
                fmt_index = int(emoji[0]) - 1
                if 0 <= fmt_index < len(MATCH_FORMATS):
                    fmt = MATCH_FORMATS[fmt_index]
                    format_votes[fmt] = format_votes.get(fmt, 0) + 1
                    logger.info(f"Format vote: {user.name} voted for {fmt}")
        
        if "Vote Winner" in embed_title:
            if emoji == "1️⃣":
                votes['team1'] = votes.get('team1', 0) + 1
                logger.info(f"Winner vote: {user.name} voted for Team 1")
            elif emoji == "2️⃣":
                votes['team2'] = votes.get('team2', 0) + 1
                logger.info(f"Winner vote: {user.name} voted for Team 2")
    except Exception as e:
        logger.error(f"Error in on_reaction_add: {e}")
        await log_error_to_channel(reaction.message.guild, f"Error in on_reaction_add: {e}")

# Run bot
if __name__ == "__main__":
    if not conn:
        logger.error("Failed to initialize database. Exiting.")
    else:
        try:
            bot.run('YOUR_BOT_TOKEN')  # Replace with your bot token
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
