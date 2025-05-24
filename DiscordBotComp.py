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
TOKEN = os.getenv('DISCORD_TOKEN')

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
    "status_command_cooldown": 30
}

# Initialize configuration first
def load_config():
    """Load configuration from file or create default"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                print("Empty config.json, creating default")
        except json.JSONDecodeError:
            print("Invalid config.json, creating default")
    else:
        print("No config.json, creating default")
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
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
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def save_applications():
    """Save applications to file"""
    with open('applications.json', 'w') as f:
        json.dump(applications, f, indent=4)

def load_applications():
    """Load applications from file"""
    global applications
    if os.path.exists('applications.json'):
        with open('applications.json', 'r') as f:
            applications = json.load(f)
        # Ensure all applications have required fields
        for uid, app in applications.items():
            app.setdefault("status", "pending")
            app.setdefault("steam_link", "N/A")
            app.setdefault("hours_played", "N/A")
            app.setdefault("submitted_at", datetime.now().isoformat())
        save_applications()

def has_staff_role(member_or_ctx):
    """Check if user has staff role"""
    member = member_or_ctx if isinstance(member_or_ctx, discord.Member) else member_or_ctx.author
    return any(role.name.lower() in config["staff_roles"] for role in member.roles)

def create_embed(title, description, color, **kwargs):
    """Create a standardized embed"""
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
    """Format seconds into human readable time"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

# Server Status Functions
async def get_server_status():
    """Get server status using A2S protocol"""
    try:
        server_address = (config["server_ip"], int(config["server_port"]))
        info = await a2s.ainfo(server_address)
        players = await a2s.aplayers(server_address)
        
        return {
            "online": True,
            "player_count": info.player_count,
            "max_players": info.max_players,
            "server_name": "HotBoxInZ",  # Force server name
            "players": players
        }
    except Exception as e:
        print(f"Error fetching server status: {str(e)}")
        return {
            "online": False,
            "player_count": 0,
            "max_players": 0,
            "server_name": "HotBoxInZ",
            "players": []
        }

def create_status_embed(status, requester=None):
    """Create server status embed"""
    color = discord.Color.green() if status["online"] else discord.Color.red()
    status_text = "🟢 Online" if status["online"] else "🔴 Offline"
    
    embed = create_embed(
        title=f"🎮 {status['server_name']} Server Status",
        description=f"**Status:** {status_text}\n**Players:** {status['player_count']}/{status['max_players']}",
        color=color,
        timestamp=True
    )
    
    if status["online"] and status["player_count"] > 0:
        if status["player_count"] <= 15:
            player_names = [p.name for p in status["players"]]
            player_list = "\n".join(f"• {name}" for name in player_names[:15])
            embed.add_field(
                name=f"👥 Players Online ({status['player_count']})",
                value=player_list or "No players found",
                inline=False
            )
        else:
            embed.add_field(
                name="👥 Players",
                value=f"Too many players to display ({status['player_count']} online)",
                inline=False
            )
    
    if requester:
        embed.set_footer(text=f"Requested by {requester} • Cooldown: {config.get('status_command_cooldown', 30)}s")
    else:
        embed.set_footer(text="Auto-updated every minute")
    
    return embed

# Tasks
@tasks.loop(minutes=1.0)
async def update_server_status():
    """Update server status message every minute"""
    global server_status_message
    channel = bot.get_channel(int(config["status_channel_id"]))
    if not channel:
        print(f"Error: Status channel {config['status_channel_id']} not found")
        return

    status = await get_server_status()
    embed = create_status_embed(status)

    try:
        if server_status_message:
            await server_status_message.edit(embed=embed)
        else:
            server_status_message = await channel.send(embed=embed)
    except Exception as e:
        print(f"Error updating server status message: {str(e)}")
        server_status_message = None

# Commands
@bot.command(name='status', help='Check the current server status and player list')
@commands.cooldown(1, config.get("status_command_cooldown", 30), commands.BucketType.user)
async def status_command(ctx):
    """Check the current server status and player list"""
    async with ctx.typing():
        status = await get_server_status()
        embed = create_status_embed(status, requester=ctx.author.name)
        await ctx.send(embed=embed)

@status_command.error
async def status_error(ctx, error):
    """Handle status command errors"""
    if isinstance(error, commands.CommandOnCooldown):
        retry_after = round(error.retry_after)
        embed = create_embed(
            title="⏳ Command Cooldown",
            description=f"Please wait **{retry_after} seconds** before checking the status again.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed, delete_after=10)
    else:
        embed = create_embed(
            title="⚠️ Error",
            description=f"An error occurred: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

# Application System Classes
class ApproveDeclineView(discord.ui.View):
    """View for approve/decline buttons on applications"""
    
    def __init__(self, applicant_id, application_data):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.application_data = application_data
        self.action_taken = False

    async def interaction_check(self, interaction):
        """Check if user can interact with buttons"""
        if self.action_taken:
            await interaction.response.send_message(
                "❌ This application has already been processed.", 
                ephemeral=True
            )
            return False
        
        if not has_staff_role(interaction.user):
            await interaction.response.send_message(
                "❌ Only staff members can process applications.", 
                ephemeral=True
            )
            return False
        
        return True

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction, button):
        """Handle approve button click"""
        await self._process_application(interaction, "approved")

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline_button(self, interaction, button):
        """Handle decline button click"""
        modal = DeclineReasonModal(self.applicant_id, self.application_data, self)
        await interaction.response.send_modal(modal)

    async def _process_application(self, interaction, action, reason=None):
        """Process application approval or decline"""
        self.action_taken = True
        for item in self.children:
            item.disabled = True

        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(int(self.applicant_id))
            
            if action == "approved":
                embed = self._create_approval_embed(user, member, interaction.user)
                await self._handle_approval(member, embed)
            else:
                embed = self._create_decline_embed(user, interaction.user, reason)
                await self._handle_decline(member, reason)
            
            # Update application data
            applications[str(self.applicant_id)]["status"] = action
            applications[str(self.applicant_id)]["processed_by"] = str(interaction.user.id)
            applications[str(self.applicant_id)]["processed_at"] = datetime.now().isoformat()
            if reason:
                applications[str(self.applicant_id)]["reason"] = reason
            save_applications()
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            print(f"Error processing application: {str(e)}")
            error_embed = create_embed(
                title="⚠️ Error",
                description=f"Error processing application: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=error_embed, view=self)

    def _create_approval_embed(self, user, member, staff_member):
        """Create approval result embed"""
        embed = create_embed(
            title="✅ Application Approved",
            description=f"Application for **{user.display_name}** has been approved!",
            color=discord.Color.green(),
            timestamp=True
        )
        
        embed.add_field(
            name="👤 Applicant",
            value=f"{user.mention}\n`{user.id}`",
            inline=True
        )
        
        embed.add_field(
            name="👨‍💼 Approved By",
            value=staff_member.mention,
            inline=True
        )
        
        embed.add_field(
            name="🔗 Steam Profile",
            value=self.application_data["steam_link"],
            inline=False
        )
        
        embed.add_field(
            name="⏱️ Hours Played",
            value=self.application_data["hours_played"],
            inline=True
        )
        
        return embed

    def _create_decline_embed(self, user, staff_member, reason):
        """Create decline result embed"""
        embed = create_embed(
            title="❌ Application Declined",
            description=f"Application for **{user.display_name}** has been declined.",
            color=discord.Color.red(),
            timestamp=True
        )
        
        embed.add_field(
            name="👤 Applicant",
            value=f"{user.mention}\n`{user.id}`",
            inline=True
        )
        
        embed.add_field(
            name="👨‍💼 Declined By",
            value=staff_member.mention,
            inline=True
        )
        
        embed.add_field(
            name="📝 Reason",
            value=reason or "No reason provided",
            inline=False
        )
        
        return embed

    async def _handle_approval(self, member, embed):
        """Handle member approval process"""
        if not member:
            embed.add_field(name="⚠️ Warning", value="Member not found in server", inline=False)
            return

        # Assign member role
        member_role = discord.utils.get(member.guild.roles, name=config["member_role"])
        if member_role:
            try:
                await member.add_roles(member_role)
                embed.add_field(
                    name="🎭 Role Assigned",
                    value=f"{member_role.mention}",
                    inline=True
                )
            except discord.Forbidden:
                embed.add_field(
                    name="⚠️ Role Error",
                    value="Failed to assign role (missing permissions)",
                    inline=True
                )
        else:
            embed.add_field(
                name="⚠️ Role Error",
                value=f"Role '{config['member_role']}' not found",
                inline=True
            )

        # Send DM to user
        try:
            dm_embed = create_embed(
                title="🎉 Application Approved!",
                description="Your application has been approved!",
                color=discord.Color.green()
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            embed.add_field(
                name="📬 DM Status",
                value="Could not send approval message to user",
                inline=True
            )

    async def _handle_decline(self, member, reason):
        """Handle member decline process"""
        if not member:
            return

        try:
            dm_embed = create_embed(
                title="📋 Application Update",
                description="Your application has been declined.",
                color=discord.Color.red()
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

class DeclineReasonModal(discord.ui.Modal, title="📝 Decline Application"):
    """Modal for entering decline reason"""
    
    reason = discord.ui.TextInput(
        label="Reason for declining (optional)",
        placeholder="Enter the reason for declining this application...",
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
        """Handle modal submission"""
        reason = self.reason.value or "No reason provided"
        await self.view._process_application(interaction, "declined", reason)

# Bot Events
@bot.event
async def on_ready():
    """Bot ready event"""
    print(f'🤖 {bot.user} is connected to Discord!')
    load_applications()
    await bot.change_presence(activity=discord.Game(name="Project Zomboid"))
    update_server_status.start()

# Application Commands
@bot.command(name='apply', help='Apply to join the Project Zomboid server')
async def apply_command(ctx):
    """Handle application command"""
    if ctx.channel.name != config["apply_channel"]:
        embed = create_embed(
            title="❌ Wrong Channel",
            description=f"Please use this command in #{config['apply_channel']}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    
    user_id = str(ctx.author.id)
    
    # Check for existing pending application
    if user_id in applications and applications[user_id]["status"] == "pending":
        embed = create_embed(
            title="⏳ Application Pending",
            description="You already have a pending application.",
            color=discord.Color.orange()
        )
        await ctx.author.send(embed=embed)
        return
    
    try:
        dm_channel = await ctx.author.create_dm()
        
        await dm_channel.send(embed=create_embed(
            title="📋 Application Process",
            description="Please follow the prompts to complete your application for the Project Zomboid server.\nYou will need to provide:\n1. Your Steam profile link\n2. Your Project Zomboid play hours\nYou have 5 minutes to respond to each prompt.",
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
            description="You took too long to respond. Please restart the application process with !apply.",
            color=discord.Color.red()
        )
        await dm_channel.send(embed=embed)
    except discord.Forbidden:
        embed = create_embed(
            title="📬 DM Error",
            description="Please enable DMs from server members to complete the application process.",
            color=discord.Color.red()
        )
        await ctx.send(f"{ctx.author.mention}", embed=embed, delete_after=15)

async def get_steam_profile(user, dm_channel):
    """Get and validate Steam profile from user"""
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="🔗 Steam Profile Link",
        description="Please provide your Steam profile link (e.g., https://steamcommunity.com/id/yourprofile or https://steamcommunity.com/profiles/123456789).\nEnsure the link is valid and publicly accessible.",
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
                title="❌ Invalid Steam Profile",
                description="Please provide a valid Steam profile link (e.g., https://steamcommunity.com/id/yourprofile).",
                color=discord.Color.red()
            )
            await dm_channel.send(embed=embed)
            
        except asyncio.TimeoutError:
            return None

async def get_hours_played(user, dm_channel):
    """Get hours played from user"""
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="⏱️ Project Zomboid Hours",
        description=f"Please enter the number of hours you have played Project Zomboid.\nYou can find this in your Steam library or profile.\nMinimum required hours: {config['min_hours']}",
        color=discord.Color.blue()
    )
    await dm_channel.send(embed=embed)
    
    try:
        hours_msg = await bot.wait_for('message', check=check, timeout=300.0)
        return hours_msg.content.strip()
    except asyncio.TimeoutError:
        return None

async def confirm_application(user, dm_channel, steam_link, hours_played):
    """Confirm application details with user"""
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="📋 Confirm Application",
        description="Please review your application details below. Type **I confirm** to submit, or anything else to cancel.",
        color=discord.Color.blue(),
        fields=[
            {
                "name": "🔗 Steam Profile",
                "value": steam_link,
                "inline": False
            },
            {
                "name": "⏱️ Hours Played",
                "value": hours_played,
                "inline": True
            }
        ]
    )
    await dm_channel.send(embed=embed)
    
    try:
        confirm_msg = await bot.wait_for('message', check=check, timeout=300.0)
        return confirm_msg.content.lower() == 'i confirm'
    except asyncio.TimeoutError:
        return False

async def submit_application(ctx, steam_link, hours_played):
    """Submit the application to staff"""
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
        description=f"{ctx.author.display_name} has submitted an application",
        color=discord.Color.gold(),
        fields=[
            {
                "name": "👤 Applicant",
                "value": f"{ctx.author.mention}\n`{ctx.author.id}`",
                "inline": True
            },
            {
                "name": "🔗 Steam Profile",
                "value": steam_link,
                "inline": False
            }
        ]
    )
    
    view = ApproveDeclineView(ctx.author.id, application_data)
    
    try:
        await apply_channel.send(embed=app_embed, view=view)
        
        success_embed = create_embed(
            title="✅ Application Submitted",
            description="Your application has been submitted and is pending review by staff.",
            color=discord.Color.green()
        )
        await ctx.author.send(embed=success_embed)
        
    except Exception as e:
        print(f"Error sending application: {str(e)}")
        error_embed = create_embed(
            title="⚠️ Error",
            description="Could not send application.",
            color=discord.Color.red()
        )
        await ctx.author.send(embed=error_embed)

# Staff Commands
@bot.command(name='approve', help='Approve a member\'s application (Staff only)')
@commands.check(has_staff_role)
async def approve_command(ctx, member: discord.Member):
    """Manually approve a member's application"""
    user_id = str(member.id)
    
    if user_id not in applications or applications[user_id]["status"] != "pending":
        embed = create_embed(
            title="❌ Error",
            description="No pending application found.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    application_data = applications[user_id]
    
    try:
        member_role = discord.utils.get(ctx.guild.roles, name=config["member_role"])
        if member_role:
            await member.add_roles(member_role)
        
        applications[user_id]["status"] = "approved"
        applications[user_id]["processed_by"] = str(ctx.author.id)
        applications[user_id]["processed_at"] = datetime.now().isoformat()
        save_applications()
        
        embed = create_embed(
            title="✅ Approved",
            description=f"{member.mention}'s application has been approved.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f"Error in approve command: {str(e)}")
        error_embed = create_embed(
            title="⚠️ Error",
            description=f"Error: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)

# Help Command
@bot.command(name='help')
async def help_command(ctx, command_name: str = None):
    """Custom help command"""
    if command_name:
        command = bot.get_command(command_name)
        if not command:
            embed = create_embed(
                title="❌ Error",
                description="Command not found.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        embed = create_embed(
            title=f"📖 {command.name}",
            description=command.help or "No description available.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    embed = create_embed(
        title="🤖 Bot Commands",
        description="Available commands:",
        color=discord.Color.blue()
    )
    
    commands_list = [
        ("!apply", "Apply to join the server"),
        ("!status", "Check server status"),
        ("!help", "Show this help message")
    ]
    
    if has_staff_role(ctx):
        commands_list.extend([
            ("!approve @user", "Approve an application"),
            ("!applications", "View applications")
        ])
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

# Error Handler
@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    if isinstance(error, commands.CommandNotFound):
        return
    
    embed = create_embed(
        title="⚠️ Error",
        description=str(error),
        color=discord.Color.red()
    )
    await ctx.send(embed=embed, delete_after=10)

# Main execution
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Error starting bot: {str(e)}")
