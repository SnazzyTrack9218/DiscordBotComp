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

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Data storage
applications = {}
server_status_message = None

# Initialize configuration
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
# Utility Functions
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
    
    # Add timestamp if requested
    if kwargs.get('timestamp', False):
        embed.timestamp = datetime.now()
    
    # Add footer if provided
    if 'footer' in kwargs:
        embed.set_footer(text=kwargs['footer'])
    
    # Add thumbnail if provided
    if 'thumbnail' in kwargs:
        embed.set_thumbnail(url=kwargs['thumbnail'])
    
    # Add fields if provided
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
            "server_name": info.server_name or config["server_name"],
            "players": players
        }
    except Exception as e:
        print(f"Error fetching server status: {str(e)}")
        return {
            "online": False,
            "player_count": 0,
            "max_players": 0,
            "server_name": config["server_name"],
            "players": []
        }

def create_status_embed(status, requester=None):
    """Create server status embed"""
    color = discord.Color.green() if status["online"] else discord.Color.red()
    status_text = "🟢 Online" if status["online"] else "🔴 Offline"
    
    # Force server name to "HotBoxInZ"
    server_name = "HotBoxInZ"
    
    embed = create_embed(
        title=f"🎮 {server_name} Server Status",
        description=f"**Status:** {status_text}\n**Players:** {status['player_count']}/{status['max_players']}",
        color=color,
        timestamp=True
    )
    
    # Add player list if online and not too many players
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
    
    # Add footer based on context
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
        
        embed.add_field(
            name="🔗 Steam Profile",
            value=self.application_data["steam_link"],
            inline=True
        )
        
        embed.add_field(
            name="⏱️ Hours Played",
            value=self.application_data["hours_played"],
            inline=True
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
                description="Congratulations! Your application to join our Project Zomboid server has been **approved**!",
                color=discord.Color.green(),
                fields=[
                    {
                        "name": "🎮 What's Next?",
                        "value": "You now have access to the server! Check out the server channels and join us in-game.",
                        "inline": False
                    },
                    {
                        "name": "📋 Server Info",
                        "value": f"**IP:** `{config['server_ip']}:{config['server_port']}`\n**Name:** {config['server_name']}",
                        "inline": False
                    }
                ],
                timestamp=True
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
                description="Your application to join our Project Zomboid server has been **declined**.",
                color=discord.Color.red(),
                fields=[
                    {
                        "name": "📝 Reason",
                        "value": reason or "No specific reason provided",
                        "inline": False
                    },
                    {
                        "name": "🔄 Reapplication",
                        "value": f"You can apply again in **{config['application_cooldown']//3600} hours**.",
                        "inline": False
                    },
                    {
                        "name": "❓ Questions?",
                        "value": "Feel free to contact our staff if you have any questions about your application.",
                        "inline": False
                    }
                ],
                timestamp=True
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

@bot.event
async def on_member_join(member):
    """Welcome new members"""
    account_age = (datetime.now(tz=member.created_at.tzinfo) - member.created_at).days
    age_display = f"{account_age} days" if account_age < 365 else f"{account_age // 365} years"
    
    embed = create_embed(
        title=f"👋 Welcome to {member.guild.name}!",
        description=f"Welcome **{member.display_name}** to our Project Zomboid community!",
        color=discord.Color.blue(),
        thumbnail=member.avatar.url if member.avatar else member.default_avatar.url,
        fields=[
            {
                "name": "📅 Account Age",
                "value": age_display,
                "inline": True
            },
            {
                "name": "📥 Joined",
                "value": f"<t:{int(datetime.now().timestamp())}:R>",
                "inline": True
            },
            {
                "name": "🎮 Getting Started",
                "value": f"Use `!apply` in #{config['apply_channel']} to join our server!",
                "inline": False
            }
        ],
        timestamp=True,
        footer=f"Member #{len(member.guild.members)}"
    )
    
    # Send to system channel or welcome channel
    channel = member.guild.system_channel or discord.utils.get(member.guild.text_channels, name="welcome")
    if channel and channel.permissions_for(member.guild.me).send_messages:
        await channel.send(embed=embed)

# Application Commands
@bot.command(name='apply', help='Apply to join the Project Zomboid server')
async def apply_command(ctx):
    """Handle application command"""
    # Check if in correct channel
    if ctx.channel.name != config["apply_channel"]:
        embed = create_embed(
            title="❌ Wrong Channel",
            description=f"Please use this command in #{config['apply_channel']}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # Delete command message
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    
    user_id = str(ctx.author.id)
    
    # Check for existing pending application
    if user_id in applications and applications[user_id]["status"] == "pending":
        embed = create_embed(
            title="⏳ Application Pending",
            description="You already have a pending application. Please wait for staff to review it.",
            color=discord.Color.orange()
        )
        await ctx.author.send(embed=embed)
        return
    
    # Check cooldown for declined applications
    if user_id in applications and applications[user_id]["status"] == "declined":
        declined_time = datetime.fromisoformat(applications[user_id]["processed_at"])
        elapsed_seconds = (datetime.now() - declined_time).total_seconds()
        
        if elapsed_seconds < config["application_cooldown"]:
            time_left = config["application_cooldown"] - elapsed_seconds
            embed = create_embed(
                title="⏰ Application Cooldown",
                description=f"Your previous application was declined. You can apply again in **{format_time_remaining(time_left)}**.",
                color=discord.Color.red()
            )
            await ctx.author.send(embed=embed)
            return
    
    try:
        dm_channel = await ctx.author.create_dm()
        
        # Start application process
        await dm_channel.send(embed=create_embed(
            title="📋 Project Zomboid Server Application",
            description="Welcome to the application process! Please answer the following questions.",
            color=discord.Color.blue(),
            fields=[
                {
                    "name": "📝 Step 1 of 3",
                    "value": "Please provide your **Steam profile link**",
                    "inline": False
                }
            ]
        ))
        
        # Get Steam profile
        steam_link = await get_steam_profile(ctx.author, dm_channel)
        if not steam_link:
            return
        
        # Get hours played
        hours_played = await get_hours_played(ctx.author, dm_channel)
        if not hours_played:
            return
        
        # Confirm application
        if not await confirm_application(ctx.author, dm_channel, steam_link, hours_played):
            return
        
        # Submit application
        await submit_application(ctx, steam_link, hours_played)
        
    except asyncio.TimeoutError:
        embed = create_embed(
            title="⏱️ Application Timeout",
            description="You took too long to respond. Please try again with `!apply`.",
            color=discord.Color.red()
        )
        await dm_channel.send(embed=embed)
    except discord.Forbidden:
        embed = create_embed(
            title="📬 DM Error",
            description="I couldn't send you a DM. Please enable DMs from server members and try again.",
            color=discord.Color.red()
        )
        await ctx.send(f"{ctx.author.mention}", embed=embed, delete_after=15)
    except Exception as e:
        print(f"Error in apply command: {str(e)}")
        embed = create_embed(
            title="⚠️ Application Error",
            description=f"An error occurred during your application: {str(e)}\n\nPlease try again or contact an admin.",
            color=discord.Color.red()
        )
        await ctx.author.send(embed=embed)

async def get_steam_profile(user, dm_channel):
    """Get and validate Steam profile from user"""
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    while True:
        try:
            steam_msg = await bot.wait_for('message', check=check, timeout=300.0)
            steam_link = steam_msg.content.strip()
            
            if STEAM_PROFILE_REGEX.match(steam_link):
                return steam_link
            
            embed = create_embed(
                title="❌ Invalid Steam Profile",
                description="That doesn't look like a valid Steam profile link. Please try again.",
                color=discord.Color.red(),
                fields=[
                    {
                        "name": "✅ Valid Examples",
                        "value": "• https://steamcommunity.com/id/yourname\n• https://steamcommunity.com/profiles/76561198000000000",
                        "inline": False
                    }
                ]
            )
            await dm_channel.send(embed=embed)
            
        except asyncio.TimeoutError:
            return None

async def get_hours_played(user, dm_channel):
    """Get hours played from user"""
    def check(m):
        return m.author == user and m.channel == dm_channel
    
    embed = create_embed(
        title="📋 Step 2 of 3",
        description="How many hours have you played **Project Zomboid**?",
        color=discord.Color.blue(),
        fields=[
            {
                "name": "💡 Tip",
                "value": "You can find this information on your Steam profile or in your Steam library.",
                "inline": False
            }
        ]
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
        title="📋 Step 3 of 3 - Confirm Application",
        description="Please review your application details below:",
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
            },
            {
                "name": "📜 Server Rules",
                "value": "By submitting this application, you confirm that you have read and agree to follow our server rules.",
                "inline": False
            },
            {
                "name": "✅ To Submit",
                "value": "Type `I confirm` to submit your application.",
                "inline": False
            }
        ]
    )
    await dm_channel.send(embed=embed)
    
    try:
        confirm_msg = await bot.wait_for('message', check=check, timeout=300.0)
        if confirm_msg.content.lower() == 'i confirm':
            return True
        
        embed = create_embed(
            title="❌ Application Cancelled",
            description="You didn't confirm the application. Please use `!apply` to start over.",
            color=discord.Color.red()
        )
        await dm_channel.send(embed=embed)
        return False
        
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
    
    # Send to apply channel
    apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
    if not apply_channel:
        embed = create_embed(
            title="⚠️ Channel Error",
            description="Application channel not found. Please contact an admin.",
            color=discord.Color.red()
        )
        await ctx.author.send(embed=embed)
        return
    
    # Create staff application embed
    app_embed = create_embed(
        title="📋 New Server Application",
        description=f"**{ctx.author.display_name}** has submitted an application",
        color=discord.Color.gold(),
        thumbnail=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url,
        fields=[
            {
                "name": "👤 Applicant",
                "value": f"{ctx.author.mention}\n`{ctx.author.id}`",
                "inline": True
            },
            {
                "name": "📅 Account Created",
                "value": f"<t:{int(ctx.author.created_at.timestamp())}:R>",
                "inline": True
            },
            {
                "name": "🔗 Steam Profile",
                "value": steam_link,
                "inline": False
            },
            {
                "name": "⏱️ Hours Played",
                "value": hours_played,
                "inline": True
            },
            {
                "name": "📅 Submitted",
                "value": f"<t:{int(datetime.now().timestamp())}:R>",
                "inline": True
            }
        ],
        timestamp=True,
        footer=f"Application ID: {ctx.author.id}"
    )
    
    view = ApproveDeclineView(ctx.author.id, application_data)
    
    try:
        await apply_channel.send(embed=app_embed, view=view)
        
        # Confirm to user
        success_embed = create_embed(
            title="✅ Application Submitted!",
            description="Your application has been successfully submitted to our staff team.",
            color=discord.Color.green(),
            fields=[
                {
                    "name": "⏳ What's Next?",
                    "value": "Our staff will review your application and get back to you soon. You'll receive a DM with the decision.",
                    "inline": False
                },
{
                    "name": "📋 Application Details",
                    "value": f"**Steam:** {steam_link}\n**Hours:** {hours_played}",
                    "inline": False
                }
            ],
            timestamp=True
        )
        await ctx.author.send(embed=success_embed)
        
    except Exception as e:
        print(f"Error sending application: {str(e)}")
        error_embed = create_embed(
            title="⚠️ Submission Error",
            description="Could not send application to staff channel. Please contact an admin.",
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
            title="❌ No Pending Application",
            description=f"No pending application found for {member.mention}.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    application_data = applications[user_id]
    
    try:
        # Assign member role
        member_role = discord.utils.get(ctx.guild.roles, name=config["member_role"])
        role_status = "Role not found"
        
        if member_role:
            try:
                await member.add_roles(member_role)
                role_status = f"✅ Assigned {member_role.mention}"
            except discord.Forbidden:
                role_status = "❌ Failed to assign role (missing permissions)"
        
        # Create result embed
        result_embed = create_embed(
            title="✅ Application Approved",
            description=f"Application for **{member.display_name}** has been approved!",
            color=discord.Color.green(),
            fields=[
                {
                    "name": "👤 Applicant",
                    "value": f"{member.mention}\n`{member.id}`",
                    "inline": True
                },
                {
                    "name": "👨‍💼 Approved By",
                    "value": ctx.author.mention,
                    "inline": True
                },
                {
                    "name": "🎭 Role Status",
                    "value": role_status,
                    "inline": True
                },
                {
                    "name": "🔗 Steam Profile",
                    "value": application_data["steam_link"],
                    "inline": False
                },
                {
                    "name": "⏱️ Hours Played",
                    "value": application_data["hours_played"],
                    "inline": True
                }
            ],
            timestamp=True
        )
        
        # Send approval 
        try:
            dm_embed = create_embed(
                title="🎉 Application Approved!",
                description="Congratulations! Your application has been **approved**!",
                color=discord.Color.green(),
                fields=[
                    {
                        "name": "🎮 Server Access",
                        "value": f"**IP:** `{config['server_ip']}:{config['server_port']}`\n**Name:** {config['server_name']}",
                        "inline": False
                    },
                    {
                        "name": "📋 Next Steps",
                        "value": "You now have access to all server channels. Welcome to the community!",
                        "inline": False
                    }
                ],
                timestamp=True
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            result_embed.add_field(
                name="📬 DM Status",
                value="❌ Could not send approval message to user",
                inline=True
            )
        
        # Update application data
        applications[user_id]["status"] = "approved"
        applications[user_id]["processed_by"] = str(ctx.author.id)
        applications[user_id]["processed_at"] = datetime.now().isoformat()
        save_applications()
        
        await ctx.send(embed=result_embed)
        
    except Exception as e:
        print(f"Error in approve command: {str(e)}")
        error_embed = create_embed(
            title="⚠️ Approval Error",
            description=f"Error processing application: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name='applications', help='View applications by status (Staff only)')
@commands.check(has_staff_role)
async def applications_command(ctx, status: str = "pending"):
    """View applications with specified status"""
    valid_statuses = ["pending", "approved", "declined", "all"]
    
    if status not in valid_statuses:
        embed = create_embed(
            title="❌ Invalid Status",
            description=f"Invalid status. Use: {', '.join(valid_statuses)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    # Filter applications
    filtered_apps = {
        uid: app for uid, app in applications.items()
        if "status" in app and (status == "all" or app["status"] == status)
    }
    
    if not filtered_apps:
        embed = create_embed(
            title="📋 No Applications Found",
            description=f"No {status} applications found.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    # Create applications embed
    status_colors = {
        "pending": discord.Color.orange(),
        "approved": discord.Color.green(),
        "declined": discord.Color.red(),
        "all": discord.Color.blue()
    }
    
    embed = create_embed(
        title=f"📋 {status.capitalize()} Applications",
        description=f"Found **{len(filtered_apps)}** application(s)",
        color=status_colors.get(status, discord.Color.blue()),
        timestamp=True
    )
    
    # Add application details (limit to 10 for readability)
    for i, (uid, app) in enumerate(list(filtered_apps.items())[:10]):
        try:
            user = await bot.fetch_user(int(uid))
            username = f"{user.display_name} ({user.name})"
        except:
            username = f"Unknown User ({uid})"
        
        submitted_time = datetime.fromisoformat(app.get('submitted_at', datetime.now().isoformat()))
        
        field_value = f"**Steam:** {app.get('steam_link', 'N/A')[:50]}{'...' if len(app.get('steam_link', '')) > 50 else ''}\n"
        field_value += f"**Hours:** {app.get('hours_played', 'N/A')}\n"
        field_value += f"**Submitted:** <t:{int(submitted_time.timestamp())}:R>"
        
        if app.get("status") == "declined" and app.get("reason"):
            field_value += f"\n**Reason:** {app['reason'][:50]}{'...' if len(app.get('reason', '')) > 50 else ''}"
        
        embed.add_field(
            name=f"{i+1}. {username}",
            value=field_value,
            inline=False
        )
    
    if len(filtered_apps) > 10:
        embed.add_field(
            name="📄 Note",
            value=f"Showing first 10 of {len(filtered_apps)} applications",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='clear', help='Clear applications by status (Staff only)')
@commands.check(has_staff_role)
async def clear_command(ctx, status: str = "all"):
    """Clear applications by status"""
    valid_statuses = ["pending", "approved", "declined", "all"]
    
    if status not in valid_statuses:
        embed = create_embed(
            title="❌ Invalid Status",
            description=f"Invalid status. Use: {', '.join(valid_statuses)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        global applications
        before_count = len(applications)
        
        if status == "all":
            applications.clear()
        else:
            applications = {
                uid: app for uid, app in applications.items()
                if app.get("status") != status
            }
        
        save_applications()
        cleared_count = before_count - len(applications)
        
        embed = create_embed(
            title="🗑️ Applications Cleared",
            description=f"Successfully cleared **{cleared_count}** application(s) with status '{status}'.",
            color=discord.Color.green(),
            fields=[
                {
                    "name": "📊 Summary",
                    "value": f"**Before:** {before_count} applications\n**After:** {len(applications)} applications\n**Cleared:** {cleared_count} applications",
                    "inline": False
                }
            ],
            timestamp=True
        )
        await ctx.send(embed=embed)
        
        # Clean up application messages in apply channel
        if cleared_count > 0:
            apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
            if apply_channel:
                deleted_messages = 0
                async for message in apply_channel.history(limit=100):
                    if (message.embeds and 
                        "Application submitted by" in message.embeds[0].description and
                        message.embeds[0].footer):
                        
                        user_id = message.embeds[0].footer.text.split("Application ID: ")[-1]
                        should_delete = (status == "all" or 
                                       user_id not in applications or 
                                       (user_id in applications and applications[user_id]["status"] != status))
                        
                        if should_delete:
                            try:
                                await message.delete()
                                deleted_messages += 1
                            except (discord.Forbidden, discord.NotFound):
                                pass
                
                if deleted_messages > 0:
                    embed.add_field(
                        name="🧹 Cleanup",
                        value=f"Deleted {deleted_messages} application message(s) from #{apply_channel.name}",
                        inline=False
                    )
                    await ctx.edit_original_response(embed=embed)
                    
    except Exception as e:
        print(f"Error in clear command: {str(e)}")
        error_embed = create_embed(
            title="⚠️ Clear Error",
            description=f"Error clearing applications: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)

# Configuration Commands
@bot.command(name='config', help='View or modify bot configuration (Admin only)')
@commands.has_permissions(administrator=True)
async def config_command(ctx, setting: str = None, *, value: str = None):
    """View or modify bot configuration"""
    if setting is None:
        # Display current configuration
        embed = create_embed(
            title="⚙️ Bot Configuration",
            description="Current bot settings:",
            color=discord.Color.blue(),
            timestamp=True
        )
        
        for key, val in config.items():
            if isinstance(val, list):
                display_value = ", ".join(val)
            else:
                display_value = str(val)
            
            embed.add_field(
                name=f"🔧 {key}",
                value=f"`{display_value}`",
                inline=True
            )
        
        embed.add_field(
            name="📝 Usage",
            value="Use `!config <setting> <value>` to modify settings",
            inline=False
        )
        
        await ctx.send(embed=embed)
        return
    
    if setting not in config:
        embed = create_embed(
            title="❌ Unknown Setting",
            description=f"Unknown setting: `{setting}`",
            color=discord.Color.red(),
            fields=[
                {
                    "name": "📋 Available Settings",
                    "value": ", ".join(f"`{key}`" for key in config.keys()),
                    "inline": False
                }
            ]
        )
        await ctx.send(embed=embed)
        return
    
    if value is None:
        # Display specific setting
        current_value = config[setting]
        if isinstance(current_value, list):
            display_value = ", ".join(current_value)
        else:
            display_value = str(current_value)
        
        embed = create_embed(
            title=f"⚙️ Configuration: {setting}",
            description=f"Current value: `{display_value}`",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        return
    
    # Update setting
    try:
        old_value = config[setting]
        
        if setting == "staff_roles":
            config[setting] = [role.strip() for role in value.split(',')]
        elif setting in ["application_cooldown", "min_hours", "status_command_cooldown"]:
            config[setting] = int(value)
        else:
            config[setting] = value
        
        save_config(config)
        
        embed = create_embed(
            title="✅ Configuration Updated",
            description=f"Successfully updated `{setting}`",
            color=discord.Color.green(),
            fields=[
                {
                    "name": "📊 Changes",
                    "value": f"**Before:** `{old_value}`\n**After:** `{config[setting]}`",
                    "inline": False
                }
            ],
            timestamp=True
        )
        await ctx.send(embed=embed)
        
    except ValueError as e:
        embed = create_embed(
            title="❌ Invalid Value",
            description=f"Invalid value for `{setting}`: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"Error updating config: {str(e)}")
        embed = create_embed(
            title="⚠️ Configuration Error",
            description=f"Error updating configuration: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

# Error Handlers
@bot.event
async def on_command_error(ctx, error):
    """Global command error handler"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore unknown commands
    
    elif isinstance(error, commands.MissingPermissions):
        embed = create_embed(
            title="🔒 Missing Permissions",
            description="You don't have permission to use this command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.CheckFailure):
        embed = create_embed(
            title="❌ Access Denied",
            description="You don't have the required role to use this command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MemberNotFound):
        embed = create_embed(
            title="👤 Member Not Found",
            description="Could not find the specified member. Please check the username/mention and try again.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.BadArgument):
        embed = create_embed(
            title="❌ Invalid Argument",
            description=f"Invalid argument provided: {str(error)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
    
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = create_embed(
            title="📝 Missing Argument",
            description=f"Missing required argument: `{error.param.name}`",
            color=discord.Color.red(),
            fields=[
                {
                    "name": "💡 Help",
                    "value": f"Use `!help {ctx.command.name}` for usage information.",
                    "inline": False
                }
            ]
        )
        await ctx.send(embed=embed, delete_after=15)
    
    else:
        print(f"Unhandled error in {ctx.command}: {str(error)}")
        embed = create_embed(
            title="⚠️ Unexpected Error",
            description="An unexpected error occurred. Please try again or contact an administrator.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)

# Help Command Override
@bot.command(name='help', help='Show help information')
async def help_command(ctx, command_name: str = None):
    """Custom help command with better formatting"""
    if command_name:
        # Show help for specific command
        command = bot.get_command(command_name)
        if not command:
            embed = create_embed(
                title="❌ Command Not Found",
                description=f"No command named `{command_name}` found.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        embed = create_embed(
            title=f"📖 Help: {command.name}",
            description=command.help or "No description available.",
            color=discord.Color.blue(),
            fields=[
                {
                    "name": "📝 Usage",
                    "value": f"`!{command.name} {command.signature}`",
                    "inline": False
                }
            ]
        )
        
        if command.aliases:
            embed.add_field(
                name="🔄 Aliases",
                value=", ".join(f"`{alias}`" for alias in command.aliases),
                inline=False
            )
        
        await ctx.send(embed=embed)
        return
    
    # Show general help
    embed = create_embed(
        title="🤖 Bot Commands",
        description=f"**{bot.user.name}** - Project Zomboid Server Bot",
        color=discord.Color.blue(),
        thumbnail=bot.user.avatar.url if bot.user.avatar else None
    )
    
    # General Commands
    general_commands = [
        ("apply", "Apply to join the server"),
        ("status", "Check server status and players"),
        ("help", "Show this help message")
    ]
    
    embed.add_field(
        name="🎮 General Commands",
        value="\n".join(f"`!{cmd}` - {desc}" for cmd, desc in general_commands),
        inline=False
    )
    
    # Staff Commands
    if has_staff_role(ctx.author):
        staff_commands = [
            ("approve <member>", "Approve a member's application"),
            ("applications [status]", "View applications by status"),
            ("clear [status]", "Clear applications by status")
        ]
        
        embed.add_field(
            name="👨‍💼 Staff Commands",
            value="\n".join(f"`!{cmd}` - {desc}" for cmd, desc in staff_commands),
            inline=False
        )
    
    # Admin Commands
    if ctx.author.guild_permissions.administrator:
        admin_commands = [
            ("config [setting] [value]", "View/modify bot configuration")
        ]
        
        embed.add_field(
            name="⚙️ Admin Commands",
            value="\n".join(f"`!{cmd}` - {desc}" for cmd, desc in admin_commands),
            inline=False
        )
    
    embed.add_field(
        name="📋 Additional Info",
        value="Use `!help <command>` for detailed information about a specific command.",
        inline=False
    )
    
    embed.set_footer(text=f"Bot Version 2.0 | Prefix: !")
    
    await ctx.send(embed=embed)

# Remove default help command
bot.remove_command('help')

# Utility Commands
@bot.command(name='ping', help='Check bot latency')
async def ping_command(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    
    if latency < 100:
        color = discord.Color.green()
        status = "🟢 Excellent"
    elif latency < 200:
        color = discord.Color.yellow()
        status = "🟡 Good"
    else:
        color = discord.Color.red()
        status = "🔴 Poor"
    
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Bot latency: **{latency}ms**\nStatus: {status}",
        color=color,
        timestamp=True
    )
    
    await ctx.send(embed=embed)

@bot.command(name='info', help='Show bot information')
async def info_command(ctx):
    """Show bot and server information"""
    embed = create_embed(
        title="ℹ️ Bot Information",
        description=f"**{bot.user.name}** - Project Zomboid Server Management Bot",
        color=discord.Color.blue(),
        thumbnail=bot.user.avatar.url if bot.user.avatar else None,
        fields=[
            {
                "name": "🎮 Server Info",
                "value": f"**Name:** {config['server_name']}\n**IP:** `{config['server_ip']}:{config['server_port']}`",
                "inline": True
            },
            {
                "name": "📊 Statistics",
                "value": f"**Guilds:** {len(bot.guilds)}\n**Users:** {len(bot.users)}\n**Applications:** {len(applications)}",
                "inline": True
            },
            {
                "name": "⚙️ Configuration",
                "value": f"**Prefix:** `!`\n**Apply Channel:** #{config['apply_channel']}\n**Member Role:** {config['member_role']}",
                "inline": False
            },
            {
                "name": "🔗 Links",
                "value": "[Bot Source](https://github.com/sourcegraph/cody) • [Support](https://discord.gg/support)",
                "inline": False
            }
        ],
        timestamp=True,
        footer=f"Bot ID: {bot.user.id}"
    )
# Initialize configuration
# config = load_config()

# Initialize configuration
config = load_config()

# Main execution
if __name__ == "__main__":
    try:
        print("🚀 Starting bot...")
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid bot token. Please check your .env file.")
    except Exception as e:
        print(f"❌ Failed to start bot: {str(e)}")
