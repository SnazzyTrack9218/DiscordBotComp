#MadeBy SnazzyTrack/RevR6
import discord
from discord.ext import commands, tasks
import asyncio
import re
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import a2s

# Load environment variables
load_dotenv()

# Constants
CONFIG_FILE = 'config.json'
STEAM_PROFILE_REGEX = re.compile(r'https?://steamcommunity\.com/(id|profiles)/[a-zA-Z0-9_-]+/?')
DEFAULT_CONFIG = {
    "staff_roles": ["staff", "headstaff"],
    "member_role": "member",
    "apply_channel": "apply",
    "application_cooldown": 86400,
    "min_hours": 0,
    "server_ip": "89.28.237.41",
    "server_port": "16269",
    "status_channel_id": "1374917255556628492",
    "server_name": "HotBoxInZ",
    "status_command_cooldown": 30,
    "welcome_channel_id": "1374133331330990094"
}

# Initialize configuration
def load_config():
    """Load configuration from file or create default"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    config = json.loads(content)
                    print("Loaded config:", config)  # Debug print
                    return config
                print("Empty config.json, creating default")
        except json.JSONDecodeError:
            print("Invalid config.json, creating default")
    else:
        print("No config.json, creating default")
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    print("Created default config:", DEFAULT_CONFIG)  # Debug print
    return DEFAULT_CONFIG

config = load_config()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Data storage
applications = {}
server_status_message = None

# Utility Functions
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def save_applications():
    with open('applications.json', 'w') as f:
        json.dump(applications, f, indent=4)

def load_applications():
    global applications
    if os.path.exists('applications.json'):
        with open('applications.json', 'r') as f:
            applications = json.load(f)
        for app in applications.values():
            app.setdefault("status", "pending")
            app.setdefault("steam_link", "N/A")
            app.setdefault("hours_played", "N/A")
            app.setdefault("submitted_at", datetime.now().isoformat())
        save_applications()

def has_staff_role(member_or_ctx):
    member = member_or_ctx if isinstance(member_or_ctx, discord.Member) else member_or_ctx.author
    return any(role.name.lower() in config["staff_roles"] for role in member.roles)

def create_embed(title, description, color, **kwargs):
    embed = discord.Embed(title=title, description=description, color=color)
    if kwargs.get('timestamp', False):
        embed.timestamp = datetime.now()
    if 'footer' in kwargs:
        embed.set_footer(text=kwargs['footer'])
    if 'thumbnail' in kwargs:
        embed.set_thumbnail(url=kwargs['thumbnail'])
    if 'fields' in kwargs:
        for field in kwargs['fields']:
            embed.add_field(
                name=field.get('name', ''),
                value=field.get('value', ''),
                inline=field.get('inline', True)
            )
    return embed

def format_time_remaining(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

# Server Status Functions
async def get_server_status():
    try:
        server_address = (config["server_ip"], int(config["server_port"]))
        info = await asyncio.wait_for(a2s.ainfo(server_address), timeout=5)
        players = await asyncio.wait_for(a2s.aplayers(server_address), timeout=5)
        return {
            "online": True,
            "player_count": info.player_count,
            "max_players": info.max_players,
            "server_name": config["server_name"],
            "players": players
        }
    except asyncio.TimeoutError:
        print(f"Server status timeout: {config['server_ip']}:{config['server_port']}")
        return {
            "online": False,
            "player_count": 0,
            "max_players": 0,
            "server_name": config["server_name"],
            "players": [],
            "error": "Server unreachable"
        }
    except Exception as e:
        print(f"Server status error: {str(e)}")
        return {
            "online": False,
            "player_count": 0,
            "max_players": 0,
            "server_name": config["server_name"],
            "players": [],
            "error": str(e)
        }

def create_status_embed(status, requester=None):
    color = discord.Color.green() if status["online"] else discord.Color.red()
    status_text = "🟢 Online" if status["online"] else "🔴 Offline"
    description = f"**Status:** {status_text}\n**Players:** {status['player_count']}/{status['max_players']}"
    if not status["online"] and "error" in status:
        description += f"\n**Error:** {status['error']}"
    
    embed = create_embed(
        title=f"🎮 {status['server_name']} Status",
        description=description,
        color=color,
        timestamp=True
    )
    
    if status["online"] and status["player_count"] > 0:
        player_names = [p.name for p in status["players"]]
        player_list = "\n".join(f"• {name}" for name in player_names[:15])
        embed.add_field(
            name=f"👥 Players ({status['player_count']})",
            value=player_list or "No players",
            inline=False
        )
    
    embed.set_footer(text=f"Requested by {requester}" if requester else "Auto-updated")
    return embed

# Tasks
@tasks.loop(minutes=1.0)
async def update_server_status():
    global server_status_message
    channel = bot.get_channel(int(config["status_channel_id"]))
    if not channel:
        print(f"Status channel {config['status_channel_id']} not found")
        return

    status = await get_server_status()
    embed = create_status_embed(status)
    try:
        if server_status_message:
            await server_status_message.edit(embed=embed)
        else:
            server_status_message = await channel.send(embed=embed)
    except Exception as e:
        print(f"Error updating status: {str(e)}")
        server_status_message = None

# Commands
@bot.command()
@commands.cooldown(1, config.get("status_command_cooldown", 30), commands.BucketType.user)
async def status(ctx):
    async with ctx.typing():
        status = await get_server_status()
        embed = create_status_embed(status, requester=ctx.author.name)
        await ctx.send(embed=embed)

@status.error
async def status_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        embed = create_embed(
            title="⏳ Cooldown",
            description=f"Wait {round(error.retry_after)}s",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    else:
        embed = create_embed(
            title="⚠️ Error",
            description=str(error),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

# Application System Classes
class RulesConfirmationView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300.0)
        self.user_id = user_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your button", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Agree", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction, _button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

class ApplicationConfirmationView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300.0)
        self.user_id = user_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your button", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Submit", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction, _button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction, _button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()

class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id, application_data):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.application_data = application_data
        self.action_taken = False

    async def interaction_check(self, interaction):
        if self.action_taken:
            await interaction.response.send_message("❌ Already processed", ephemeral=True)
            return False
        if not has_staff_role(interaction.user):
            await interaction.response.send_message("❌ Staff only", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction, _button):
        await self._process_application(interaction, "approved")

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline_button(self, interaction, _button):
        modal = DeclineReasonModal(self.applicant_id, self.application_data, self)
        await interaction.response.send_modal(modal)

    async def _process_application(self, interaction, action, reason=None):
        self.action_taken = True
        for item in self.children:
            item.disabled = True

        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(int(self.applicant_id))
            embed = self._create_approval_embed(user, member, interaction.user) if action == "approved" else self._create_decline_embed(user, interaction.user, reason)
            
            if action == "approved":
                await self._handle_approval(member, embed)
            else:
                await self._handle_decline(member, reason)
            
            applications[str(self.applicant_id)]["status"] = action
            applications[str(self.applicant_id)]["processed_by"] = str(interaction.user.id)
            applications[str(self.applicant_id)]["processed_at"] = datetime.now().isoformat()
            if reason:
                applications[str(self.applicant_id)]["reason"] = reason
            save_applications()
            
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            print(f"Error processing application: {str(e)}")
            embed = create_embed(title="⚠️ Error", description=str(e), color=discord.Color.red())
            await interaction.response.edit_message(embed=embed, view=self)

    def _create_approval_embed(self, user, _member, staff_member):
        embed = create_embed(
            title="✅ Approved",
            description=f"{user.display_name}'s application approved!",
            color=discord.Color.green(),
            timestamp=True
        )
        embed.add_field(name="👤 Applicant", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="👨‍💼 By", value=staff_member.mention, inline=True)
        embed.add_field(name="🔗 Steam", value=self.application_data["steam_link"], inline=False)
        embed.add_field(name="⏱️ Hours", value=self.application_data["hours_played"], inline=True)
        return embed

    def _create_decline_embed(self, user, staff_member, reason):
        embed = create_embed(
            title="❌ Declined",
            description=f"{user.display_name}'s application declined.",
            color=discord.Color.red(),
            timestamp=True
        )
        embed.add_field(name="👤 Applicant", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="👨‍💼 By", value=staff_member.mention, inline=True)
        embed.add_field(name="📝 Reason", value=reason or "None", inline=False)
        return embed

    async def _handle_approval(self, member, embed):
        if not member:
            embed.add_field(name="⚠️ Warning", value="Member not found", inline=False)
            return
        member_role = discord.utils.get(member.guild.roles, name=config["member_role"])
        if member_role:
            try:
                await member.add_roles(member_role)
                embed.add_field(name="🎭 Role", value=member_role.mention, inline=True)
            except discord.Forbidden:
                embed.add_field(name="⚠️ Error", value="No role permission", inline=True)
        else:
            embed.add_field(name="⚠️ Error", value=f"Role {config['member_role']} not found", inline=True)
        try:
            await member.send(embed=create_embed(
                title="🎉 Approved!",
                description="You now have access to the server.",
                color=discord.Color.green()
            ))
        except discord.Forbidden:
            embed.add_field(name="📬 DM", value="Could not DM user", inline=True)

    async def _handle_decline(self, member, reason):
        if not member:
            return
        try:
            await member.send(embed=create_embed(
                title="📋 Update",
                description=f"Application declined.\n**Reason:** {reason or 'None'}",
                color=discord.Color.red()
            ))
        except discord.Forbidden:
            pass

class DeclineReasonModal(discord.ui.Modal, title="📝 Decline Reason"):
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Why was this declined?",
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, applicant_id, application_data, view):
        super().__init__()
        self.applicant_id = applicant_id
        self.application_data = application_data
        self.view = view
    
    async def on_submit(self, interaction):
        await self.view._process_application(interaction, "declined", self.reason.value or "None")

# Bot Events
@bot.event
async def on_ready():
    print(f'🤖 {bot.user} connected!')
    load_applications()
    await bot.change_presence(activity=discord.Game(name="Project Zomboid"))
    update_server_status.start()

@bot.event
async def on_member_join(member):
    """Send welcome message to new members"""
    welcome_channel = bot.get_channel(int(config["welcome_channel_id"]))
    if not welcome_channel:
        print(f"Error: Welcome channel ID {config['welcome_channel_id']} not found")
        return

    # Calculate account age
    account_age = (datetime.now() - member.created_at).days // 365
    join_date = member.joined_at.strftime("%Y-%m-%d")
    
    # Create welcome embed
    embed = create_embed(
        title=f"🎉 Welcome {member.display_name}!",
        description=(
            f"Thanks for joining the **{config['server_name']}** server community!\n\n"
            f"Please use the `!apply` command in the <#{discord.utils.get(member.guild.text_channels, name=config['apply_channel']).id}> channel to join."
        ),
        color=discord.Color.green(),
        fields=[
            {"name": "Account Age", "value": f"{account_age} years", "inline": True},
            {"name": "Joined", "value": f"{join_date}", "inline": True}
        ],
        thumbnail=member.avatar.url if member.avatar else member.default_avatar.url
    )
    
    try:
        await welcome_channel.send(embed=embed)
    except discord.Forbidden:
        print(f"Error: Bot lacks permission to send messages in channel ID {config['welcome_channel_id']}")
    except Exception as e:
        print(f"Error sending welcome message: {str(e)}")

# Application Commands
@bot.command()
async def apply(ctx):
    member_role = discord.utils.get(ctx.guild.roles, name=config["member_role"])
    if member_role in ctx.author.roles:
        embed = create_embed(
            title="❌ Already Member",
            description="You already have the member role.",
            color=discord.Color.red()
        )
        await ctx.author.send(embed=embed)
        return

    if ctx.channel.name != config["apply_channel"]:
        embed = create_embed(
            title="❌ Wrong Channel",
            description=f"Use in #{config['apply_channel']}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    
    user_id = str(ctx.author.id)
    if user_id in applications and applications[user_id]["status"] == "pending":
        embed = create_embed(
            title="⏳ Pending",
            description="You have a pending application.",
            color=discord.Color.orange()
        )
        await ctx.author.send(embed=embed)
        return
    
    try:
        dm_channel = await ctx.author.create_dm()
        rules_embed = create_embed(
            title="📋 Application",
            description="Confirm you agree to the rules.",
            color=discord.Color.blue()
        )
        view = RulesConfirmationView(ctx.author.id)
        await dm_channel.send(embed=rules_embed, view=view)
        
        await view.wait()
        if not view.confirmed:
            embed = create_embed(
                title="❌ Cancelled",
                description="Rules not confirmed.",
                color=discord.Color.red()
            )
            await dm_channel.send(embed=embed)
            return
        
        await dm_channel.send(embed=create_embed(
            title="📋 Process",
            description="Provide:\n- Steam profile link\n- Project Zomboid hours",
            color=discord.Color.blue()
        ))
        
        steam_link = await get_steam_profile(ctx.author, dm_channel)
        if not steam_link:
            return
        
        hours_played = await get_hours_played(ctx.author, dm_channel)
        if not hours_played:
            return
        
        if not await confirm_application(ctx.author, dm_channel, steam_link, hours_played):
            return
        
        await submit_application(ctx, steam_link, hours_played)
        
    except asyncio.TimeoutError:
        embed = create_embed(
            title="⏱️ Timeout",
            description="Restart with !apply.",
            color=discord.Color.red()
        )
        await dm_channel.send(embed=embed)
    except discord.Forbidden:
        embed = create_embed(
            title="📬 DM Error",
            description="Enable DMs from server members.",
            color=discord.Color.red()
        )
        await ctx.send(f"{ctx.author.mention}", embed=embed, delete_after=15)

async def get_steam_profile(user, dm_channel):
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="📝 Step 1/3",
        description="Provide Steam profile link.",
        color=discord.Color.blue()
    )
    await dm_channel.send(embed=embed)
    
    while True:
        try:
            steam_msg = await bot.wait_for('message', check=check, timeout=300.0)
            steam_link = steam_msg.content.strip()
            if STEAM_PROFILE_REGEX.match(steam_link):
                return steam_link
            embed = create_embed(
                title="❌ Invalid",
                description="Valid Steam link required.",
                color=discord.Color.red()
            )
            await dm_channel.send(embed=embed)
        except asyncio.TimeoutError:
            return None

async def get_hours_played(user, dm_channel):
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="📝 Step 2/3",
        description="Enter Project Zomboid hours.",
        color=discord.Color.blue()
    )
    await dm_channel.send(embed=embed)
    
    try:
        hours_msg = await bot.wait_for('message', check=check, timeout=300.0)
        return hours_msg.content.strip()
    except asyncio.TimeoutError:
        return None

async def confirm_application(user, dm_channel, steam_link, hours_played):
    embed = create_embed(
        title="📝 Step 3/3",
        description="Review and submit:",
        color=discord.Color.blue(),
        fields=[
            {"name": "Steam", "value": steam_link, "inline": False},
            {"name": "Hours", "value": hours_played, "inline": True}
        ]
    )
    view = ApplicationConfirmationView(user.id)
    await dm_channel.send(embed=embed, view=view)
    
    await view.wait()
    if not view.confirmed:
        embed = create_embed(
            title="❌ Cancelled",
            description="Application cancelled.",
            color=discord.Color.red()
        )
        await dm_channel.send(embed=embed)
        return False
    return True

async def submit_application(ctx, steam_link, hours_played):
    user_id = str(ctx.author.id)
    application_data = {
        "steam_link": steam_link,
        "hours_played": hours_played,
        "status": "pending",
        "submitted_at": datetime.now().isoformat()
    }
    applications[user_id] = application_data
    save_applications()
    
    apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
    if not apply_channel:
        embed = create_embed(
            title="⚠️ Error",
            description="Application channel not found.",
            color=discord.Color.red()
        )
        await ctx.author.send(embed=embed)
        return
    
    app_embed = create_embed(
        title="📋 New Application",
        description=f"{ctx.author.display_name}'s application",
        color=discord.Color.gold(),
        fields=[
            {"name": "👤 Applicant", "value": f"{ctx.author.mention}\n`{user_id}`", "inline": True},
            {"name": "🔗 Steam", "value": steam_link, "inline": False},
            {"name": "⏱️ Hours", "value": hours_played, "inline": True}
        ]
    )
    
    view = ApproveDeclineView(ctx.author.id, application_data)
    try:
        await apply_channel.send(embed=app_embed, view=view)
        success_embed = create_embed(
            title="✅ Submitted",
            description="Application sent to staff.",
            color=discord.Color.green(),
            fields=[{"name": "Details", "value": f"**Steam:** {steam_link}\n**Hours:** {hours_played}", "inline": False}]
        )
        await ctx.author.send(embed=success_embed)
    except Exception as e:
        print(f"Error sending application: {str(e)}")
        embed = create_embed(title="⚠️ Error", description="Failed to send.", color=discord.Color.red())
        await ctx.author.send(embed=embed)

# Staff Commands
@bot.command()
@commands.check(has_staff_role)
async def approve(ctx, member: discord.Member):
    user_id = str(member.id)
    if user_id not in applications or applications[user_id]["status"] != "pending":
        embed = create_embed(
            title="❌ Error",
            description="No pending application.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    application_data = applications[user_id]
    try:
        member_role = discord.utils.get(ctx.guild.roles, name=config["member_role"])
        if not member_role:
            embed = create_embed(
                title="⚠️ Error",
                description=f"Role {config['member_role']} not found.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        await member.add_roles(member_role)
        applications[user_id]["status"] = "approved"
        applications[user_id]["processed_by"] = str(ctx.author.id)
        applications[user_id]["processed_at"] = datetime.now().isoformat()
        save_applications()
        
        embed = create_embed(
            title="✅ Approved",
            description=f"{member.mention} approved by {ctx.author.mention}.",
            color=discord.Color.green(),
            timestamp=True,
            fields=[
                {"name": "🔗 Steam", "value": application_data["steam_link"], "inline": False},
                {"name": "⏱️ Hours", "value": application_data["hours_played"], "inline": True}
            ]
        )
        await ctx.send(embed=embed)
        try:
            await member.send(embed=create_embed(
                title="🎉 Approved!",
                description="You have access to the server.",
                color=discord.Color.green()
            ))
        except discord.Forbidden:
            embed.add_field(name="📬 DM", value="Could not DM user", inline=True)
            await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = create_embed(
            title="⚠️ Error",
            description="No role permission.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    except Exception as e:
        print(f"Approve error: {str(e)}")
        embed = create_embed(title="⚠️ Error", description=str(e), color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
@commands.check(has_staff_role)
async def applications(ctx):
    if not applications:
        embed = create_embed(
            title="📋 Applications",
            description="None found.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, delete_after=10)
        return

    apps_per_page = 5
    pages = []
    current_page = []
    count = 0

    for user_id, app in applications.items():
        try:
            user = await bot.fetch_user(int(user_id))
            user_display = user.display_name
        except discord.NotFound:
            user_display = f"Unknown ({user_id})"

        status_emoji = {"pending": "⏳", "approved": "✅", "declined": "❌"}.get(app["status"], "❓")
        app_info = (
            f"**User:** {user_display} (`{user_id}`)\n"
            f"**Status:** {status_emoji} {app['status'].capitalize()}\n"
            f"**Steam:** {app['steam_link']}\n"
            f"**Hours:** {app['hours_played']}\n"
            f"**Submitted:** {app['submitted_at'][:10]}\n"
        )
        if "processed_by" in app:
            try:
                processor = await bot.fetch_user(int(app["processed_by"]))
                app_info += f"**Processed By:** {processor.display_name}\n"
            except discord.NotFound:
                app_info += f"**Processed By:** Unknown\n"
        if app["status"] == "declined" and "reason" in app:
            app_info += f"**Reason:** {app['reason']}\n"

        current_page.append({"name": f"Application {count + 1}", "value": app_info, "inline": False})
        count += 1
        if count % apps_per_page == 0:
            pages.append(current_page)
            current_page = []

    if current_page:
        pages.append(current_page)

    class ApplicationPaginator(discord.ui.View):
        def __init__(self, pages):
            super().__init__(timeout=60)
            self.pages = pages
            self.current_page = 0

        @discord.ui.button(label="Previous", style=discord.ButtonStyle.grey, disabled=True)
        async def previous_button(self, interaction, _button):
            self.current_page -= 1
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = False
            embed = create_embed(
                title="📋 Applications",
                description=f"Page {self.current_page + 1}/{len(self.pages)}",
                color=discord.Color.blue(),
                fields=self.pages[self.current_page]
            )
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="Next", style=discord.ButtonStyle.grey)
        async def next_button(self, interaction, _button):
            self.current_page += 1
            self.children[1].disabled = self.current_page == len(self.pages) - 1
            self.children[0].disabled = False
            embed = create_embed(
                title="📋 Applications",
                description=f"Page {self.current_page + 1}/{len(self.pages)}",
                color=discord.Color.blue(),
                fields=self.pages[self.current_page]
            )
            await interaction.response.edit_message(embed=embed, view=self)

    embed = create_embed(
        title="📋 Applications",
        description=f"Page 1/{len(pages)}",
        color=discord.Color.blue(),
        fields=pages[0]
    )
    view = ApplicationPaginator(pages)
    if len(pages) == 1:
        view.children[1].disabled = True
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.check(has_staff_role)
async def clear(ctx, status: str):
    status = status.lower()
    valid_statuses = ["pending", "approved", "declined"]
    if status not in valid_statuses:
        embed = create_embed(
            title="❌ Invalid",
            description=f"Use: {', '.join(valid_statuses)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return

    global applications
    count = sum(1 for app in applications.values() if app["status"] == status)
    if count == 0:
        embed = create_embed(
            title="📋 Clear",
            description=f"No {status} applications.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, delete_after=10)
        return

    applications = {uid: app for uid, app in applications.items() if app["status"] != status}
    save_applications()
    embed = create_embed(
        title="✅ Cleared",
        description=f"Cleared {count} {status} applications.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx, command_name: str = None):
    if command_name:
        command = bot.get_command(command_name)
        if not command:
            embed = create_embed(title="❌ Error", description="Command not found.", color=discord.Color.red())
            await ctx.send(embed=embed)
            return
        embed = create_embed(title=f"📖 {command.name}", description=command.help or "No description.", color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    
    embed = create_embed(title="🤖 Commands", description="Available commands:", color=discord.Color.blue())
    commands_list = [
        ("!apply", "Apply to join"),
        ("!status", "Check server status"),
        ("!help", "Show help")
    ]
    if has_staff_role(ctx):
        commands_list.extend([
            ("!approve @user", "Approve application"),
            ("!applications", "View applications"),
            ("!clear <status>", "Clear applications")
        ])
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    embed = create_embed(title="⚠️ Error", description=str(error), color=discord.Color.red())
    await ctx.send(embed=embed, delete_after=10)

# Main execution
if __name__ == "__main__":
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        print(f"Error starting bot: {str(e)}")
