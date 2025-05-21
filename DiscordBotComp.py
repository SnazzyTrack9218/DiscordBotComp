import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta
import re
import os
import json
import logging
from dotenv import load_dotenv
from typing import Optional, Dict, List, Union

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ZomboidApplicationBot")

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    logger.critical("No Discord token found. Set the DISCORD_TOKEN environment variable.")
    raise ValueError("Discord token not found in environment variables")

# Constants
STEAM_PROFILE_REGEX = re.compile(r'https?://steamcommunity\.com/(id|profiles)/[a-zA-Z0-9_-]+/?')
APPLICATION_COOLDOWN = 86400  # 24 hours in seconds
CONFIG_FILE = "bot_config.json"
APPLICATIONS_FILE = "applications.json"
RESPONSE_TIMEOUT = 300  # 5 minutes

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Configuration defaults
DEFAULT_CONFIG = {
    "staff_roles": ["staff", "headstaff", "admin", "moderator"],
    "member_role": "member",
    "apply_channel": "apply",
    "welcome_channel": None,  # Use system channel by default
    "min_hours": 0,  # No minimum hours
    "application_cooldown": APPLICATION_COOLDOWN,
    "response_timeout": RESPONSE_TIMEOUT,
    "custom_questions": []
}

# Load or create configuration
def load_config() -> Dict[str, Union[str, int, List[str], None]]:
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            logger.info("Configuration loaded successfully")
            return config
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning(f"Failed to load config: {e}. Creating default config")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config: Dict[str, Union[str, int, List[str], None]]) -> None:
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        logger.info("Configuration saved successfully")
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to save config: {e}")

# Load or create applications database
def load_applications() -> Dict[str, Dict]:
    try:
        with open(APPLICATIONS_FILE, 'r') as f:
            applications = json.load(f)
            logger.info("Applications loaded successfully")
            return applications
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning(f"Failed to load applications: {e}. Creating empty applications file")
        empty_db = {"pending": {}, "approved": {}, "declined": {}}
        save_applications(empty_db)
        return empty_db

def save_applications(applications: Dict[str, Dict]) -> None:
    try:
        with open(APPLICATIONS_FILE, 'w') as f:
            json.dump(applications, f, indent=4)
        logger.info("Applications saved successfully")
    except (PermissionError, OSError) as e:
        logger.error(f"Failed to save applications: {e}")

# Application data
config = load_config()
applications = load_applications()

class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id: int, application_data: Dict):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.application_data = application_data
        self.action_taken = False
        self.add_item(discord.ui.Button(
            label="Steam Profile", 
            url=application_data["steam_link"],
            style=discord.ButtonStyle.link
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.action_taken:
            await interaction.response.send_message("This application has already been processed.", ephemeral=True)
            return False
        
        if not any(role.name.lower() in config["staff_roles"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff members can process applications.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_button")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.action_taken = True
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.url is None:
                item.disabled = True
        
        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(self.applicant_id)
            
            if member:
                member_role = discord.utils.get(guild.roles, name=config["member_role"])
                role_message = (f"Assigned {member_role.mention} role." if member_role and await member.add_roles(member_role)
                               else f"Member role '{config['member_role']}' not found or bot lacks permissions.")
                
                applications["pending"].pop(str(self.applicant_id), None)
                applications["approved"][str(self.applicant_id)] = {
                    **self.application_data,
                    "approved_by": interaction.user.id,
                    "approved_at": datetime.now().isoformat()
                }
                save_applications(applications)
                
                embed = discord.Embed(
                    description=f"✅ Application for {user.mention} **approved** by {interaction.user.mention}!\n{role_message}",
                    color=discord.Color.green()
                )
                embed.add_field(name="Steam Profile", value=self.application_data["steam_link"], inline=False)
                embed.add_field(name="Hours Played", value=f"{self.application_data['hours_played']} hours", inline=True)
                embed.add_field(name="Applied At", value=f"<t:{int(datetime.fromisoformat(self.application_data['timestamp']).timestamp())}:R>", inline=True)
                
                try:
                    dm_channel = await user.create_dm()
                    welcome_embed = discord.Embed(
                        title="Application Approved! 🎉",
                        description=f"Your application to join {guild.name} has been approved!\nYou now have access to member channels.",
                        color=discord.Color.green()
                    )
                    await dm_channel.send(embed=welcome_embed)
                except discord.DiscordException:
                    logger.warning(f"Failed to send DM to {user.id}")
                    
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        description=f"⚠️ User with ID {self.applicant_id} is no longer in the server.",
                        color=discord.Color.orange()
                    ), 
                    view=self
                )
        except Exception as e:
            logger.error(f"Error in approve button: {e}")
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"⚠️ An error occurred: {str(e)}", color=discord.Color.red()),
                view=self
            )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        reason_modal = DeclineReasonModal(self)
        await interaction.response.send_modal(reason_modal)

class DeclineReasonModal(discord.ui.Modal):
    def __init__(self, view: ApproveDeclineView):
        super().__init__(title="Decline Application")
        self.view = view
        self.reason = discord.ui.TextInput(
            label="Reason for declining (optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Enter reason why application was declined...",
            required=False,
            max_length=1000
        )
        self.add_item(self.reason)
        
    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.view.action_taken = True
        for item in self.view.children:
            if isinstance(item, discord.ui.Button) and item.url is None:
                item.disabled = True
        
        reason_text = self.reason.value.strip() if self.reason.value else "No reason provided"
        
        try:
            user = await bot.fetch_user(self.view.applicant_id)
            applications["pending"].pop(str(self.view.applicant_id), None)
            applications["declined"][str(self.view.applicant_id)] = {
                **self.view.application_data,
                "declined_by": interaction.user.id,
                "declined_at": datetime.now().isoformat(),
                "reason": reason_text
            }
            save_applications(applications)
            
            embed = discord.Embed(
                description=f"❌ Application for {user.mention} **declined** by {interaction.user.mention}.",
                color=discord.Color.red()
            )
            embed.add_field(name="Steam Profile", value=self.view.application_data["steam_link"], inline=False)
            embed.add_field(name="Hours Played", value=f"{self.view.application_data['hours_played']} hours", inline=True)
            embed.add_field(name="Reason", value=reason_text, inline=False)
            
            try:
                dm_channel = await user.create_dm()
                decline_embed = discord.Embed(
                    title="Application Status Update",
                    description=f"Your application to join the server has been declined.",
                    color=discord.Color.red()
                )
                if reason_text != "No reason provided":
                    decline_embed.add_field(name="Reason", value=reason_text)
                decline_embed.add_field(name="What next?", value="You can apply again after 24 hours or contact a staff member if you have questions.")
                await dm_channel.send(embed=decline_embed)
            except discord.DiscordException:
                logger.warning(f"Failed to send DM to {user.id}")
            
            await interaction.response.edit_message(embed=embed, view=self.view)
            await asyncio.sleep(300)
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass
                
        except Exception as e:
            logger.error(f"Error in decline modal: {e}")
            await interaction.response.edit_message(
                embed=discord.Embed(description=f"⚠️ An error occurred: {str(e)}", color=discord.Color.red()),
                view=self.view
            )

@bot.event
async def on_ready() -> None:
    logger.info(f'{bot.user} has connected to Discord!')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, 
        name="for !apply | !help"
    ))
    logger.info("Bot is ready!")

@bot.event
async def on_member_join(member: discord.Member) -> None:
    channel = None
    if config.get("welcome_channel"):
        channel = member.guild.get_channel(int(config["welcome_channel"]))
    if not channel or not channel.permissions_for(member.guild.me).send_messages:
        channel = member.guild.system_channel or next(
            (c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages), None
        )
    
    if not channel:
        logger.warning(f"No suitable channel found to welcome {member.display_name}")
        return
        
    account_age = (datetime.now(tz=member.created_at.tzinfo) - member.created_at).days
    account_age_str = f"{account_age // 365} years" if account_age >= 365 else f"{account_age} days"
    
    embed = discord.Embed(
        title=f"Welcome {member.display_name}!",
        description="Thanks for joining our Project Zomboid server!",
        color=discord.Color.blue()
    )
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    elif member.default_avatar:
        embed.set_thumbnail(url=member.default_avatar.url)
        
    embed.add_field(name="Discord Profile", value=member.mention, inline=True)
    embed.add_field(name="Account Age", value=account_age_str, inline=True)
    embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
    
    apply_channel = discord.utils.get(member.guild.text_channels, name=config["apply_channel"])
    if apply_channel and apply_channel.permissions_for(member.guild.me).send_messages:
        embed.add_field(
            name="How to Apply",
            value=f"Use the `!apply` command in {apply_channel.mention} to get access to our Project Zomboid server.",
            inline=False
        )
    
    await channel.send(embed=embed)
    
@bot.command()
async def apply(ctx: commands.Context) -> None:
    logger.info(f"Apply command invoked by {ctx.author.id} in channel {ctx.channel.id}")
    apply_channel = discord.utils.get(ctx.guild.text_channels, name=config["apply_channel"])
    if not apply_channel or not apply_channel.permissions_for(ctx.guild.me).send_messages:
        embed = discord.Embed(
            description=f"❗ Application channel not found or I lack permissions. Contact staff.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=30)
        await ctx.message.delete()
        return

    if isinstance(ctx.channel, discord.DMChannel) or ctx.channel != apply_channel:
        channel_ref = apply_channel.mention if apply_channel else f"#{config['apply_channel']}"
        embed = discord.Embed(
            description=f"❗ Please use this command in {channel_ref}.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=30)
        await ctx.message.delete()
        return

    user_id = str(ctx.author.id)
    last_application = None
    for status in ["pending", "approved", "declined"]:
        if user_id in applications[status]:
            last_application = applications[status][user_id]
            break
    
    if last_application:
        applied_at = datetime.fromisoformat(last_application["timestamp"])
        cooldown_until = applied_at + timedelta(seconds=config["application_cooldown"])
        if datetime.now() < cooldown_until:
            time_left = cooldown_until - datetime.now()
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            embed = discord.Embed(
                description=f"❗ You must wait **{hours}h {minutes}m** before applying again.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, delete_after=30)
            await ctx.message.delete()
            return
        if user_id in applications["pending"]:
            embed = discord.Embed(
                description="❗ You have a pending application. Wait for staff review.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, delete_after=30)
            await ctx.message.delete()
            return
    
    member_role = discord.utils.get(ctx.guild.roles, name=config["member_role"])
    if member_role and member_role in ctx.author.roles:
        embed = discord.Embed(
            description=f"❗ You already have the {member_role.mention} role!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=30)
        await ctx.message.delete()
        return
    
    await ctx.message.delete()
    
    try:
        dm_channel = await ctx.author.create_dm()
    except discord.Forbidden:
        logger.error(f"Cannot DM user {ctx.author.name} ({ctx.author.id})")
        embed = discord.Embed(
            description="❗ I cannot send you direct messages. Enable DMs from server members and try again.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=30)
        return

    progress_embed = discord.Embed(
        title="Project Zomboid Server Application",
        description="I've sent you a DM to complete your application! Check your direct messages.",
        color=discord.Color.blue()
    )
    progress_msg = await ctx.send(embed=progress_embed, delete_after=15)
    
    def check(m: discord.Message) -> bool:
        return m.author == ctx.author and m.channel == dm_channel

    application_data = {
        "user_id": ctx.author.id,
        "username": f"{ctx.author.name}",
        "timestamp": datetime.now().isoformat(),
        "guild_id": ctx.guild.id,
        "guild_name": ctx.guild.name
    }
    
    try:
        welcome_embed = discord.Embed(
            title="Project Zomboid Server Application",
            description=(
                "Thanks for applying to join our Project Zomboid server!\n\n"
                "I'll ask you a few questions to complete your application.\n"
                "Type `cancel` at any time to cancel the application."
            ),
            color=discord.Color.blue()
        )
        welcome_embed.add_field(name="Step 1/3", value="First, I'll need your Steam profile link", inline=False)
        await dm_channel.send(embed=welcome_embed)
        
        steam_embed = discord.Embed(
            description="🔗 Please provide your Steam profile link (must be a valid URL).",
            color=discord.Color.blue()
        )
        steam_embed.set_footer(text="Example: https://steamcommunity.com/id/username")
        await dm_channel.send(embed=steam_embed)

        while True:
            steam_msg = await bot.wait_for('message', check=check, timeout=config["response_timeout"])
            if steam_msg.content.lower() == 'cancel':
                await dm_channel.send(embed=discord.Embed(description="Application cancelled.", color=discord.Color.red()))
                return
            steam_link = steam_msg.content.strip()
            if STEAM_PROFILE_REGEX.match(steam_link):
                application_data["steam_link"] = steam_link
                break
            await dm_channel.send(embed=discord.Embed(
                description="❗ Invalid Steam profile link. Try again or type `cancel`.",
                color=discord.Color.red()
            ))

        progress_embed = discord.Embed(
            title="Step 2/3",
            description="How many hours have you played Project Zomboid? (Enter a number)",
            color=discord.Color.blue()
        )
        await dm_channel.send(embed=progress_embed)

        while True:
            hours_msg = await bot.wait_for('message', check=check, timeout=config["response_timeout"])
            if hours_msg.content.lower() == 'cancel':
                await dm_channel.send(embed=discord.Embed(description="Application cancelled.", color=discord.Color.red()))
                return
            hours_played = hours_msg.content.strip()
            try:
                hours = float(hours_played.replace(',', ''))
                if hours < config["min_hours"]:
                    await dm_channel.send(embed=discord.Embed(
                        description=f"❗ Minimum {config['min_hours']} hours required. Application cancelled.",
                        color=discord.Color.red()
                    ))
                    return
                application_data["hours_played"] = hours
                break
            except ValueError:
                await dm_channel.send(embed=discord.Embed(
                    description="❗ Please enter a valid number of hours or type `cancel`.",
                    color=discord.Color.red()
                ))

        custom_answers = {}
        custom_questions = config.get("custom_questions", [])
        for i, question in enumerate(custom_questions):
            progress_embed = discord.Embed(
                title=f"Additional Question {i+1}/{len(custom_questions)}",
                description=question,
                color=discord.Color.blue()
            )
            await dm_channel.send(embed=progress_embed)
            answer_msg = await bot.wait_for('message', check=check, timeout=config["response_timeout"])
            if answer_msg.content.lower() == 'cancel':
                await dm_channel.send(embed=discord.Embed(description="Application cancelled.", color=discord.Color.red()))
                return
            custom_answers[f"question_{i+1}"] = {"question": question, "answer": answer_msg.content}
        
        application_data["custom_answers"] = custom_answers

        confirmation_embed = discord.Embed(
            title="Step 3/3 - Review and Confirm",
            description=(
                "Review your application and confirm by typing `I confirm` or type `cancel` to quit.\n\n"
                "By confirming, you agree to follow the server rules."
            ),
            color=discord.Color.blue()
        )
        confirmation_embed.add_field(name="Steam Profile", value=application_data["steam_link"], inline=False)
        confirmation_embed.add_field(name="Hours Played", value=str(application_data["hours_played"]), inline=False)
        for i, qa in enumerate(custom_answers.values()):
            confirmation_embed.add_field(name=f"Q: {qa['question']}", value=f"A: {qa['answer']}", inline=False)
        await dm_channel.send(embed=confirmation_embed)

        while True:
            confirm_msg = await bot.wait_for('message', check=check, timeout=config["response_timeout"])
            if confirm_msg.content.lower() == 'cancel':
                await dm_channel.send(embed=discord.Embed(description="Application cancelled.", color=discord.Color.red()))
                return
            if confirm_msg.content.lower() == 'i confirm':
                break
            await dm_channel.send(embed=discord.Embed(
                description="Please type `I confirm` to submit or `cancel` to quit.",
                color=discord.Color.yellow()
            ))

        applications["pending"][user_id] = application_data
        save_applications(applications)

        hours_display = f"{application_data['hours_played']:,}"
        application_embed = discord.Embed(
            title="📝 New Application",
            description=f"Submitted by {ctx.author.mention}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        application_embed.add_field(name="Steam Profile", value=application_data["steam_link"], inline=False)
        application_embed.add_field(name="Hours Played", value=hours_display, inline=False)
        for i, qa in enumerate(custom_answers.values()):
            application_embed.add_field(name=f"Q: {qa['question']}", value=f"A: {qa['answer']}", inline=False)
        application_embed.set_footer(text=f"User ID: {ctx.author.id}")
        
        view = ApproveDeclineView(applicant_id=ctx.author.id, application_data=application_data)
        await apply_channel.send(embed=application_embed, view=view)
        
        success_embed = discord.Embed(
            title="✅ Application Submitted!",
            description="Your application has been submitted for review. Staff will review it soon.",
            color=discord.Color.green()
        )
        await dm_channel.send(embed=success_embed)

    except asyncio.TimeoutError:
        await dm_channel.send(embed=discord.Embed(
            title="⏱️ Application Timed Out",
            description="You took too long to respond. Start a new application when ready.",
            color=discord.Color.red()
        ))
    except Exception as e:
        logger.error(f"Error in apply command for user {ctx.author.id}: {e}")
        await dm_channel.send(embed=discord.Embed(
            title="⚠️ Error",
            description="Something went wrong. Try again later or contact staff.",
            color=discord.Color.red()
        ))

@bot.command()
@commands.has_permissions(administrator=True)
async def config(ctx: commands.Context, setting: Optional[str] = None, *, value: Optional[str] = None) -> None:
    if not setting:
        embed = discord.Embed(
            title="Bot Configuration",
            description="Current configuration settings:",
            color=discord.Color.blue()
        )
        for key, val in config.items():
            if key == "staff_roles":
                embed.add_field(name="Staff Roles", value=", ".join(val), inline=False)
            elif key == "custom_questions":
                embed.add_field(name="Custom Questions", value=f"{len(val)} questions configured", inline=False)
            else:
                embed.add_field(name=key.replace("_", " ").title(), value=str(val), inline=False)
        embed.add_field(
            name="Usage",
            value="Use `!config <setting> <value>` to change a setting\nExample: `!config member_role verified`",
            inline=False
        )
        await ctx.send(embed=embed)
        return
        
    setting = setting.lower()
    if setting not in config:
        await ctx.send(f"Unknown setting: `{setting}`. Use `!config` to see available settings.")
        return
        
    if value is None:
        current = config[setting]
        if isinstance(current, list):
            current = ", ".join(current)
        await ctx.send(f"Current value of `{setting}`: {current}")
        return
    
    if setting == "staff_roles":
        config[setting] = [role.strip() for role in value.split(",")]
    elif setting == "application_cooldown":
        try:
            config[setting] = int(value)
        except ValueError:
            await ctx.send("Cooldown must be a number (seconds)")
            return
    elif setting == "min_hours":
        try:
            config[setting] = float(value)
        except ValueError:
            await ctx.send("Min hours must be a number")
            return
    elif setting == "response_timeout":
        try:
            config[setting] = int(value)
        except ValueError:
            await ctx.send("Response timeout must be a number (seconds)")
            return
    elif setting == "welcome_channel":
        channel_id = value[2:-1] if value.startswith("<#") and value.endswith(">") else value
        channel = ctx.guild.get_channel(int(channel_id))
        if not channel or not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send("Invalid channel ID or I lack permissions to send messages there")
            return
        config[setting] = channel_id
    else:
        config[setting] = value
    
    save_config(config)
    await ctx.send(f"✅ Updated `{setting}` to: {value}")
    logger.info(f"Config updated: {setting} = {value}")

@bot.command()
@commands.has_permissions(administrator=True)
async def list_questions(ctx: commands.Context) -> None:
    if "custom_questions" not in config or not config["custom_questions"]:
        await ctx.send("No custom questions configured.")
        return
    
    embed = discord.Embed(
        title="Custom Application Questions",
        description="These questions will be asked during the application process:",
        color=discord.Color.blue()
    )
    for i, question in enumerate(config["custom_questions"], 1):
        embed.add_field(name=f"Question {i}", value=question, inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(kick_members=True)
async def applications(ctx: commands.Context, status: str = "pending") -> None:
    status = status.lower()
    if status not in ["pending", "approved", "declined", "all"]:
        await ctx.send("Invalid status. Use `pending`, `approved`, `declined`, or `all`.")
        return
    
    if not any(role.name.lower() in config["staff_roles"] for role in ctx.author.roles):
        await ctx.send("You don't have permission to use this command.")
        return
    
    embed = discord.Embed(title=f"{status.title()} Applications", color=discord.Color.blue())
    application_data = applications[status] if status != "all" else {**applications["pending"], **applications["approved"], **applications["declined"]}
    
    if not application_data:
        embed.description = f"No {status} applications found."
        await ctx.send(embed=embed)
        return
    
    sorted_apps = sorted(
        application_data.items(),
        key=lambda x: datetime.fromisoformat(x[1]["timestamp"]),
        reverse=True
    )
    
    count = 0
    for user_id, app in sorted_apps[:10]:
        count += 1
        try:
            user = await bot.fetch_user(int(user_id))
            user_name = f"{user.name} ({user.mention})"
        except:
            user_name = f"Unknown User (ID: {user_id})"
        
        timestamp = datetime.fromisoformat(app["timestamp"])
        field_value = (
            f"Applied: <t:{int(timestamp.timestamp())}:R>\n"
            f"Steam: [Link]({app['steam_link']})\n"
            f"Hours: {app['hours_played']}"
        )
        
        if user_id in applications["approved"]:
            try:
                approved_by = await bot.fetch_user(app["approved_by"])
                field_value += f"\nApproved by: {approved_by.name}"
            except:
                field_value += "\nApproved by: Unknown Staff"
        elif user_id in applications["declined"]:
            try:
                declined_by = await bot.fetch_user(app["declined_by"])
                field_value += f"\nDeclined by: {declined_by.name}"
                if app.get("reason"):
                    reason = app["reason"][:97] + "..." if len(app["reason"]) > 100 else app["reason"]
                    field_value += f"\nReason: {reason}"
            except:
                field_value += "\nDeclined by: Unknown Staff"
        
        embed.add_field(name=user_name, value=field_value, inline=False)
    
    if len(application_data) > 10:
        embed.set_footer(text=f"Showing 10 of {len(application_data)} {status} applications. Use !application_details <user> for more info.")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(kick_members=True)
async def application_details(ctx: commands.Context, user: discord.User) -> None:
    if not any(role.name.lower() in config["staff_roles"] for role in ctx.author.roles):
        await ctx.send("You don't have permission to use this command.")
        return
    
    user_id = str(user.id)
    app_data = None
    status = None
    
    for app_status in ["pending", "approved", "declined"]:
        if user_id in applications[app_status]:
            app_data = applications[app_status][user_id]
            status = app_status
            break
    
    if not app_data:
        await ctx.send(f"No application found for {user.mention}.")
        return
    
    embed = discord.Embed(
        title=f"Application Details - {user.name}",
        description=f"Status: **{status.title()}**",
        color=discord.Color.blue(),
        timestamp=datetime.fromisoformat(app_data["timestamp"])
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="Steam Profile", value=app_data["steam_link"], inline=False)
    embed.add_field(name="Hours Played", value=str(app_data["hours_played"]), inline=False)
    embed.add_field(name="Applied", value=f"<t:{int(datetime.fromisoformat(app_data['timestamp']).timestamp())}:F>", inline=False)
    
    if "custom_answers" in app_data and app_data["custom_answers"]:
        for qa in app_data["custom_answers"].values():
            embed.add_field(name=f"Q: {qa['question']}", value=f"A: {qa['answer']}", inline=False)
    
    if status == "approved":
        try:
            approved_by = await bot.fetch_user(app_data["approved_by"])
            approved_at = datetime.fromisoformat(app_data["approved_at"])
            embed.add_field(name="Approved By", value=f"{approved_by.mention} at <t:{int(approved_at.timestamp())}:F>", inline=False)
        except:
            embed.add_field(name="Approved By", value="Unknown Staff", inline=False)
    elif status == "declined":
        try:
            declined_by = await bot.fetch_user(app_data["declined_by"])
            declined_at = datetime.fromisoformat(app_data["declined_at"])
            embed.add_field(name="Declined By", value=f"{declined_by.mention} at <t:{int(declined_at.timestamp())}:F>", inline=False)
            if "reason" in app_data:
                embed.add_field(name="Reason", value=app_data["reason"], inline=False)
        except:
            embed.add_field(name="Declined By", value="Unknown Staff", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx: commands.Context, command: Optional[str] = None) -> None:
    logger.info(f"Help command invoked by {ctx.author.id} for command: {command or 'none'}")
    if command:
        cmd = bot.get_command(command)
        if not cmd:
            await ctx.send(f"Command `{command}` not found.", delete_after=30)
            return
        embed = discord.Embed(
            title=f"Help: !{cmd.name}",
            description=getattr(cmd, 'help', None) or "No description available.",
            color=discord.Color.blue()
        )
        if hasattr(cmd, 'signature'):
            embed.add_field(name="Usage", value=f"!{cmd.name} {cmd.signature}", inline=False)
        await ctx.send(embed=embed, delete_after=30)
        return
    
    embed = discord.Embed(
        title="Project Zomboid Application Bot Help",
        description="Available commands:",
        color=discord.Color.blue()
    )
    is_admin = ctx.author.guild_permissions.administrator
    is_staff = any(role.name.lower() in config["staff_roles"] for role in ctx.author.roles)
    
    public_cmds = []
    for cmd in bot.commands:
        if not cmd.checks:  # Public commands have no checks
            public_cmds.append(f"**!{cmd.name}** - {getattr(cmd, 'help', None) or 'No description'}")
    if public_cmds:
        embed.add_field(name="📝 Public Commands", value="\n".join(public_cmds), inline=False)
    
    if is_staff:
        staff_cmds = []
        for cmd in bot.commands:
            if hasattr(cmd, 'checks') and cmd.checks:
                requires_admin = any(
                    isinstance(check, commands.has_permissions) and check.kwargs.get('administrator', False)
                    for check in cmd.checks
                )
                if not getattr(cmd, 'hidden', False) and (not requires_admin or is_admin):
                    staff_cmds.append(f"**!{cmd.name}** - {getattr(cmd, 'help', None) or 'No description'}")
        if staff_cmds:
            embed.add_field(name="🛡️ Staff Commands", value="\n".join(staff_cmds), inline=False)
    
    embed.set_footer(text="Type !help <command> for more details.")
    await ctx.send(embed=embed, delete_after=30)

@bot.command()
@commands.has_permissions(administrator=True)
async def add_question(ctx: commands.Context, *, question: str) -> None:
    if "custom_questions" not in config:
        config["custom_questions"] = []
    config["custom_questions"].append(question)
    save_config(config)
    await ctx.send(f"✅ Added question: '{question}'\nTotal questions: {len(config['custom_questions'])}")
    logger.info(f"Added custom question: {question}")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove_question(ctx: commands.Context, index: int) -> None:
    if "custom_questions" not in config or not config["custom_questions"]:
        await ctx.send("No custom questions configured.")
        return
    if index < 1 or index > len(config["custom_questions"]):
        await ctx.send(f"Invalid index. Available range: 1-{len(config['custom_questions'])}")
        return
    removed = config["custom_questions"].pop(index - 1)
    save_config(config)
    await ctx.send(f"✅ Removed question: '{removed}'")
    logger.info(f"Removed custom question: {removed}")

@bot.command()
@commands.has_permissions(administrator=True)
async def clear_applications(ctx: commands.Context, status: str = "none") -> None:
    valid_statuses = ["pending", "approved", "declined", "all"]
    if status not in valid_statuses:
        await ctx.send(f"❗ Invalid status. Use one of: {', '.join(valid_statuses)}")
        return
    
    confirmation = await ctx.send(f"⚠️ Are you sure you want to clear all **{status}** applications? Reply with `yes` to confirm.")
    
    def check(m: discord.Message) -> bool:
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        response = await bot.wait_for('message', check=check, timeout=30.0)
        if response.content.lower() != 'yes':
            await ctx.send("Operation cancelled.")
            return
        
        if status == "all":
            for status_key in ["pending", "approved", "declined"]:
                applications[status_key] = {}
        else:
            applications[status] = {}
        save_applications(applications)
        await ctx.send(f"✅ Cleared all **{status}** applications.")
        logger.info(f"Cleared {status} applications")
    
    except asyncio.TimeoutError:
        await ctx.send("Operation timed out.")

@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Error in command '{ctx.command}': {error}")
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Unknown command. Type `!help` for a list of commands.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: {error}", delete_after=10)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use this command.", delete_after=10)
    elif isinstance(error, commands.CommandInvokeError):
        # Log the original exception for debugging
        logger.error(f"Original exception: {error.original}")
        await ctx.send("An error occurred while executing the command.", delete_after=10)
    else:
        await ctx.send(f"An unexpected error occurred: {error}", delete_after=10)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
