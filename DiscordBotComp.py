import discord
from discord.ext import commands, tasks
import asyncio
import re
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import a2s  # For Source Query Protocol

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
    "status_channel_id": "1374917255556628492"
}

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Data storage
applications = {}
server_status_message = None

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()

def save_applications():
    with open('applications.json', 'w') as f:
        json.dump(applications, f, indent=4)

def load_applications():
    global applications
    if os.path.exists('applications.json'):
        with open('applications.json', 'r') as f:
            applications = json.load(f)
        for uid, app in applications.items():
            app.setdefault("status", "pending")
            app.setdefault("steam_link", "N/A")
            app.setdefault("hours_played", "N/A")
            app.setdefault("submitted_at", datetime.now().isoformat())
        save_applications()

def has_staff_role(member_or_ctx):
    member = member_or_ctx if isinstance(member_or_ctx, discord.Member) else member_or_ctx.author
    return any(role.name.lower() in config["staff_roles"] for role in member.roles)

async def get_server_status():
    try:
        server_address = (config["server_ip"], int(config["server_port"]))
        info = await a2s.ainfo(server_address)
        return {
            "online": True,
            "player_count": info.player_count,
            "max_players": info.max_players,
            "server_name": info.server_name or "Project Zomboid Server"
        }
    except Exception as e:
        print(f"Error fetching server status: {str(e)}")
        return {"online": False, "player_count": 0, "max_players": 0, "server_name": "Project Zomboid Server"}

@tasks.loop(minutes=5.0)
async def update_server_status():
    global server_status_message
    channel = bot.get_channel(int(config["status_channel_id"]))
    if not channel:
        print(f"Error: Channel {config['status_channel_id']} not found")
        return

    status = await get_server_status()
    embed = discord.Embed(
        title=status["server_name"],
        color=discord.Color.green() if status["online"] else discord.Color.red(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Status", value="Online" if status["online"] else "Offline", inline=True)
    embed.add_field(name="Players", value=f"{status['player_count']}/{status['max_players']}", inline=True)
    embed.set_footer(text="Last updated")

    try:
        if server_status_message:
            await server_status_message.edit(embed=embed)
        else:
            server_status_message = await channel.send(embed=embed)
    except Exception as e:
        print(f"Error updating server status message: {str(e)}")
        server_status_message = None

@bot.event
async def on_ready():
    print(f'{bot.user} is connected to Discord!')
    load_applications()
    await bot.change_presence(activity=discord.Game(name="Project Zomboid"))
    update_server_status.start()

@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title=f"Welcome {member.display_name}!",
        description="Thanks for joining our Project Zomboid server community!",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    account_age = (datetime.now(tz=member.created_at.tzinfo) - member.created_at).days
    embed.add_field(name="Account Age", value=f"{account_age} days" if account_age < 365 else f"{account_age // 365} years", inline=True)
    embed.add_field(name="Joined", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
    embed.set_footer(text=f"Please use the !apply command in the #{config['apply_channel']} channel to join.")
    
    channel = member.guild.system_channel or discord.utils.get(member.guild.text_channels, name="welcome")
    if channel and channel.permissions_for(member.guild.me).send_messages:
        await channel.send(embed=embed)

class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id, application_data):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.application_data = application_data
        self.action_taken = False
        self.custom_id = f"approve_decline_{applicant_id}"

    async def interaction_check(self, interaction):
        if self.action_taken:
            await interaction.response.send_message("This application has already been processed.", ephemeral=True)
            return False
        if not has_staff_role(interaction.user):
            await interaction.response.send_message("Only staff can process applications.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_button")
    async def approve(self, interaction, button):
        self.action_taken = True
        for item in self.children:
            item.disabled = True
            
        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(int(self.applicant_id))
            
            result_embed = discord.Embed(
                description=f"✅ Application for {user.mention} **approved** by {interaction.user.mention}!", 
                color=discord.Color.green()
            )
            result_embed.add_field(name="Steam Profile", value=self.application_data["steam_link"], inline=True)
            result_embed.add_field(name="Hours Played", value=self.application_data["hours_played"], inline=True)
            
            if member:
                member_role = discord.utils.get(guild.roles, name=config["member_role"])
                if member_role:
                    try:
                        await member.add_roles(member_role)
                        result_embed.add_field(name="Role", value=f"Assigned {member_role.mention}", inline=False)
                    except discord.Forbidden:
                        result_embed.add_field(name="Role", value="Failed to assign role (missing permissions)", inline=False)
                else:
                    result_embed.add_field(name="Role", value=f"Role '{config['member_role']}' not found", inline=False)
                
                try:
                    await member.send(embed=discord.Embed(
                        title="Application Approved!",
                        description="Your application to join our Project Zomboid server has been approved! Welcome to the community!",
                        color=discord.Color.green()
                    ))
                except discord.Forbidden:
                    result_embed.add_field(name="Note", value="Could not DM user about approval", inline=False)
            else:
                result_embed.add_field(name="Error", value="Member not found in server", inline=False)
                
            applications[str(self.applicant_id)]["status"] = "approved"
            applications[str(self.applicant_id)]["processed_by"] = str(interaction.user.id)
            applications[str(self.applicant_id)]["processed_at"] = datetime.now().isoformat()
            save_applications()
            
            await interaction.response.edit_message(embed=result_embed, view=self)
            
        except Exception as e:
            print(f"Error in approve button: {str(e)}")
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"⚠️ Error processing application: {str(e)}", color=discord.Color.red()),
                view=self
            )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction, button):
        self.action_taken = True
        for item in self.children:
            item.disabled = True
            
        try:
            user = await bot.fetch_user(self.applicant_id)
            modal = DeclineReasonModal(self.applicant_id, self.application_data)
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            print(f"Error in decline button: {str(e)}")
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"⚠️ Error processing application: {str(e)}", color=discord.Color.red()),
                view=self
            )

class DeclineReasonModal(discord.ui.Modal, title="Decline Application"):
    reason = discord.ui.TextInput(
        label="Reason for declining",
        placeholder="Enter reason (optional)",
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, applicant_id, application_data):
        super().__init__()
        self.applicant_id = applicant_id
        self.application_data = application_data
    
    async def on_submit(self, interaction):
        reason_text = self.reason.value or "No reason provided"
        
        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(int(self.applicant_id))
            
            result_embed = discord.Embed(
                description=f"❌ Application for {user.mention} **declined** by {interaction.user.mention}", 
                color=discord.Color.red()
            )
            result_embed.add_field(name="Steam Profile", value=self.application_data["steam_link"], inline=True)
            result_embed.add_field(name="Hours Played", value=self.application_data["hours_played"], inline=True)
            result_embed.add_field(name="Reason", value=reason_text, inline=False)
            
            if member:
                try:
                    dm_embed = discord.Embed(
                        title="Application Status",
                        description="Your application to join our Project Zomboid server has been declined.",
                        color=discord.Color.red()
                    )
                    dm_embed.add_field(name="Reason", value=reason_text, inline=False)
                    dm_embed.add_field(name="Next Steps", 
                                       value=f"You can apply again in {config['application_cooldown']//3600} hours.", 
                                       inline=False)
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    result_embed.add_field(name="Note", value="Could not DM user about decline", inline=False)
            
            applications[str(self.applicant_id)]["status"] = "declined"
            applications[str(self.applicant_id)]["reason"] = reason_text
            applications[str(self.applicant_id)]["processed_by"] = str(interaction.user.id)
            applications[str(self.applicant_id)]["processed_at"] = datetime.now().isoformat()
            save_applications()
            
            await interaction.response.send_message(embed=result_embed, ephemeral=True)
            
            view = ApproveDeclineView(self.applicant_id, self.application_data)
            for item in view.children:
                item.disabled = True
            await interaction.message.edit(embed=result_embed, view=view)
            
            await asyncio.sleep(300)
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass
                
        except Exception as e:
            print(f"Error in decline modal: {str(e)}")
            await interaction.response.send_message(
                f"⚠️ Error processing application: {str(e)}", 
                ephemeral=True
            )

@bot.command()
async def apply(ctx):
    if ctx.channel.name != config["apply_channel"]:
        await ctx.send(
            embed=discord.Embed(
                description=f"❗ Please use this command in the #{config['apply_channel']} channel.", 
                color=discord.Color.red()
            ),
            delete_after=10
        )
        return
    
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    
    user_id = str(ctx.author.id)
    if user_id in applications and applications[user_id]["status"] == "pending":
        await ctx.author.send(
            embed=discord.Embed(
                description="❗ You already have a pending application. Please wait for staff to review it.",
                color=discord.Color.red()
            )
        )
        return
    
    if user_id in applications and applications[user_id]["status"] == "declined":
        declined_time = datetime.fromisoformat(applications[user_id]["processed_at"])
        elapsed_seconds = (datetime.now() - declined_time).total_seconds()
        if elapsed_seconds < config["application_cooldown"]:
            time_left = config["application_cooldown"] - elapsed_seconds
            hours_left = int(time_left // 3600)
            minutes_left = int((time_left % 3600) // 60)
            await ctx.author.send(
                embed=discord.Embed(
                    description=f"❗ Your previous application was declined. You can apply again in {hours_left}h {minutes_left}m.",
                    color=discord.Color.red()
                )
            )
            return
    
    try:
        dm_channel = await ctx.author.create_dm()
        
        def check(m):
            return m.author == ctx.author and m.channel == dm_channel
        
        await dm_channel.send(
            embed=discord.Embed(
                title="Project Zomboid Server Application",
                description="🔗 Please provide your Steam profile link (must be a valid URL).",
                color=discord.Color.blue()
            )
        )
        
        while True:
            steam_msg = await bot.wait_for('message', check=check, timeout=300.0)
            steam_link = steam_msg.content.strip()
            if STEAM_PROFILE_REGEX.match(steam_link):
                break
            await dm_channel.send(
                embed=discord.Embed(
                    description="❗ That doesn't look like a valid Steam profile link. Try again.",
                    color=discord.Color.red()
                )
            )
        
        await dm_channel.send(
            embed=discord.Embed(
                description="🕒 How many hours have you played Project Zomboid?",
                color=discord.Color.blue()
            )
        )
        
        hours_msg = await bot.wait_for('message', check=check, timeout=300.0)
        hours_played = hours_msg.content.strip()
        
        rules_embed = discord.Embed(
            title="Application Summary",
            description="Please review your application and confirm you've read our server rules.",
            color=discord.Color.blue()
        )
        rules_embed.add_field(name="Steam Profile", value=steam_link, inline=True)
        rules_embed.add_field(name="Hours Played", value=hours_played, inline=True)
        rules_embed.add_field(name="To Complete", value="Reply with `I confirm` to acknowledge you've read the rules.", inline=False)
        
        await dm_channel.send(embed=rules_embed)
        
        confirm_msg = await bot.wait_for('message', check=check, timeout=300.0)
        if confirm_msg.content.lower() != 'i confirm':
            await dm_channel.send(
                embed=discord.Embed(
                    description="❌ You didn't confirm reading the rules. Application cancelled.",
                    color=discord.Color.red()
                )
            )
            return
        
        application_data = {
            "steam_link": steam_link,
            "hours_played": hours_played,
            "status": "pending",
            "submitted_at": datetime.now().isoformat()
        }
        
        applications[user_id] = application_data
        save_applications()
        
        apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
        if apply_channel:
            app_embed = discord.Embed(
                title="New Server Application",
                description=f"📝 **Application submitted by {ctx.author.mention}**",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            app_embed.add_field(name="Steam Profile", value=steam_link, inline=True)
            app_embed.add_field(name="Hours Played", value=hours_played, inline=True)
            app_embed.set_footer(text=f"User ID: {ctx.author.id}")
            
            view = ApproveDeclineView(ctx.author.id, application_data)
            try:
                await apply_channel.send(embed=app_embed, view=view)
            except Exception as e:
                print(f"Error sending application message: {str(e)}")
                await dm_channel.send(
                    embed=discord.Embed(
                        description="⚠️ Error: Could not send application to staff channel. Please contact an admin.",
                        color=discord.Color.red()
                    )
                )
                return
            
            await dm_channel.send(
                embed=discord.Embed(
                    title="Application Submitted",
                    description="✅ Your application has been submitted! Staff will review it soon.",
                    color=discord.Color.green()
                )
            )
        else:
            await dm_channel.send(
                embed=discord.Embed(
                    description="⚠️ Error: Application channel not found. Please contact an admin.",
                    color=discord.Color.red()
                )
            )
            
    except asyncio.TimeoutError:
        await dm_channel.send(
            embed=discord.Embed(
                description="⏱️ You took too long to respond. Application cancelled.",
                color=discord.Color.red()
            )
        )
    except discord.Forbidden:
        await ctx.send(
            f"{ctx.author.mention}, I couldn't send you a DM. Please enable DMs from server members and try again.",
            delete_after=15
        )
    except Exception as e:
        print(f"Error in apply command: {str(e)}")
        await ctx.author.send(
            embed=discord.Embed(
                description=f"⚠️ An error occurred: {str(e)}. Please try again or contact an admin.",
                color=discord.Color.red()
            )
        )

@bot.command()
@commands.check(has_staff_role)
async def approve(ctx, member: discord.Member):
    """Approve a member's application"""
    user_id = str(member.id)
    
    if user_id not in applications or applications[user_id]["status"] != "pending":
        await ctx.send(
            embed=discord.Embed(
                description=f"❗ No pending application found for {member.mention}.",
                color=discord.Color.red()
            )
        )
        return
    
    application_data = applications[user_id]
    
    try:
        guild = ctx.guild
        member_role = discord.utils.get(guild.roles, name=config["member_role"])
        
        result_embed = discord.Embed(
            description=f"✅ Application for {member.mention} **approved** by {ctx.author.mention}!",
            color=discord.Color.green()
        )
        result_embed.add_field(name="Steam Profile", value=application_data["steam_link"], inline=True)
        result_embed.add_field(name="Hours Played", value=application_data["hours_played"], inline=True)
        
        if member_role:
            try:
                await member.add_roles(member_role)
                result_embed.add_field(name="Role", value=f"Assigned {member_role.mention}", inline=False)
            except discord.Forbidden:
                result_embed.add_field(name="Role", value="Failed to assign role (missing permissions)", inline=False)
        else:
            result_embed.add_field(name="Role", value=f"Role '{config['member_role']}' not found", inline=False)
        
        try:
            await member.send(embed=discord.Embed(
                title="Application Approved!",
                description="Your application to join our Project Zomboid server has been approved! Welcome to the community!",
                color=discord.Color.green()
            ))
        except discord.Forbidden:
            result_embed.add_field(name="Note", value="Could not DM user about approval", inline=False)
        
        applications[user_id]["status"] = "approved"
        applications[user_id]["processed_by"] = str(ctx.author.id)
        applications[user_id]["processed_at"] = datetime.now().isoformat()
        save_applications()
        
        await ctx.send(embed=result_embed)
        
        apply_channel = discord.utils.get(guild.text_channels, name=config["apply_channel"])
        if apply_channel:
            async for message in apply_channel.history(limit=100):
                if message.embeds and "Application submitted by" in message.embeds[0].description and str(member.id) in message.embeds[0].footer.text:
                    view = ApproveDeclineView(member.id, application_data)
                    for item in view.children:
                        item.disabled = True
                    await message.edit(embed=message.embeds[0], view=view)
                    break
        
    except Exception as e:
        print(f"Error in approve command: {str(e)}")
        await ctx.send(
            embed=discord.Embed(
                description=f"⚠️ Error processing application: {str(e)}",
                color=discord.Color.red()
            )
        )

@bot.command()
@commands.check(has_staff_role)
async def clear(ctx, status: str = "all"):
    """Clear applications by status (pending, approved, declined, or all)"""
    if status not in ["pending", "approved", "declined", "all"]:
        await ctx.send(
            embed=discord.Embed(
                description="❗ Invalid status. Use: pending, approved, declined, or all",
                color=discord.Color.red()
            )
        )
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
        
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Cleared {cleared_count} application(s) with status '{status}'.",
                color=discord.Color.green()
            )
        )
        
        apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
        if apply_channel and cleared_count > 0:
            async for message in apply_channel.history(limit=100):
                if message.embeds and "Application submitted by" in message.embeds[0].description:
                    user_id = message.embeds[0].footer.text.split("User ID: ")[-1]
                    if (status == "all" or (user_id in applications and applications[user_id]["status"] != status) or user_id not in applications):
                        try:
                            await message.delete()
                        except discord.Forbidden:
                            print(f"Error deleting application message for user {user_id}: Missing permissions")
                        except discord.NotFound:
                            pass
                            
    except Exception as e:
        print(f"Error in clear command: {str(e)}")
        await ctx.send(
            embed=discord.Embed(
                description=f"⚠️ Error clearing applications: {str(e)}",
                color=discord.Color.red()
            )
        )

@bot.command()
@commands.check(has_staff_role)
async def applications(ctx, status: str = "pending"):
    """View applications with the specified status"""
    if status not in ["pending", "approved", "declined", "all"]:
        await ctx.send("Invalid status. Use: pending, approved, declined, or all")
        return
        
    filtered_apps = {
        uid: app for uid, app in applications.items()
        if "status" in app and (status == "all" or app["status"] == status)
    }
    
    if not filtered_apps:
        await ctx.send(f"No {status} applications found.")
        return
        
    embed = discord.Embed(
        title=f"{status.capitalize()} Applications",
        description=f"Found {len(filtered_apps)} application(s)",
        color=discord.Color.blue()
    )
    
    for i, (uid, app) in enumerate(list(filtered_apps.items())[:10]):
        try:
            user = await bot.fetch_user(int(uid))
            username = user.name
        except:
            username = f"Unknown User ({uid})"
            
        embed.add_field(
            name=f"{i+1}. {username}",
            value=(
                f"Steam: {app.get('steam_link', 'N/A')[:30]}...\n"
                f"Hours: {app.get('hours_played', 'N/A')}\n"
                f"Submitted: <t:{int(datetime.fromisoformat(app.get('submitted_at', datetime.now().isoformat())).timestamp())}:R>"
            ),
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def config_set(ctx, setting: str, *, value: str):
    """Change a bot configuration setting"""
    if setting not in config:
        await ctx.send(f"Unknown setting: {setting}. Available settings: {', '.join(config.keys())}")
        return
        
    if setting == "staff_roles":
        config[setting] = [role.strip() for role in value.split(',')]
    elif setting == "application_cooldown":
        try:
            config[setting] = int(value)
        except ValueError:
            await ctx.send("Cooldown must be a number in seconds.")
            return
    elif setting == "min_hours":
        try:
            config[setting] = int(value)
        except ValueError:
            await ctx.send("Minimum hours must be a number.")
            return
    else:
        config[setting] = value
        
    save_config(config)
    await ctx.send(f"✅ Updated {setting} to: {config[setting]}")

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
