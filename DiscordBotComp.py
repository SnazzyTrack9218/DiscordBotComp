import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import re
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

STEAM_PROFILE_REGEX = re.compile(r'https?://steamcommunity\.com/(id|profiles)/[a-zA-Z0-9_-]+/?')

class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id, steam_link):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.steam_link = steam_link
        self.action_taken = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.action_taken:
            await interaction.response.send_message("This application has already been processed.", ephemeral=True)
            return False
        if not any(role.name.lower() in ["staff", "headstaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff or headstaff can process applications.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_button")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action_taken = True
        for item in self.children:
            item.disabled = True
        try:
            user = await bot.fetch_user(self.applicant_id)
            guild = interaction.guild
            member = guild.get_member(self.applicant_id)
            if member:
                member_role = discord.utils.get(guild.roles, name="member")
                if member_role:
                    try:
                        await member.add_roles(member_role)
                        await interaction.response.edit_message(embed=discord.Embed(description=f"✅ Application for {user.mention} **approved** by {interaction.user.mention}! Assigned member role.\n**Steam Profile:** {self.steam_link}", color=discord.Color.green()), view=self)
                    except discord.Forbidden:
                        await interaction.response.edit_message(embed=discord.Embed(description=f"✅ Application for {user.mention} **approved** by {interaction.user.mention}! Failed to assign member role (bot lacks permissions).\n**Steam Profile:** {self.steam_link}", color=discord.Color.green()), view=self)
                else:
                    await interaction.response.edit_message(embed=discord.Embed(description=f"✅ Application for {user.mention} **approved** by {interaction.user.mention}! member role not found.\n**Steam Profile:** {self.steam_link}", color=discord.Color.green()), view=self)
            else:
                await interaction.response.edit_message(embed=discord.Embed(description=f"⚠️ Member not found in guild.\n**Steam Profile:** {self.steam_link}", color=discord.Color.red()), view=self)
        except discord.NotFound:
            await interaction.response.edit_message(embed=discord.Embed(description=f"⚠️ User not found.\n**Steam Profile:** {self.steam_link}", color=discord.Color.red()), view=self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action_taken = True
        for item in self.children:
            item.disabled = True
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.edit_message(embed=discord.Embed(description=f"❌ Application for {user.mention} **declined** by {interaction.user.mention}.\n**Steam Profile:** {self.steam_link}", color=discord.Color.red()), view=self)
            await asyncio.sleep(300)  # Auto-delete after 5 minutes for declined applications
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass
        except discord.NotFound:
            await interaction.response.edit_message(embed=discord.Embed(description=f"⚠️ User not found.\n**Steam Profile:** {self.steam_link}", color=discord.Color.red()), view=self)
            await asyncio.sleep(300)  # Auto-delete after 5 minutes for declined applications
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    bot.add_view(ApproveDeclineView(applicant_id=0, steam_link=""))

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel or next((c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages), None)
    if not channel:
        return
    account_age = (datetime.now(tz=member.created_at.tzinfo) - member.created_at).days // 365
    embed = discord.Embed(title=f"Welcome {member.display_name}!", color=discord.Color.blue())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="Discord Profile", value=member.mention, inline=False)
    embed.add_field(name="Account Age", value=f"{account_age} years", inline=False)
    embed.set_footer(text="Please use the !apply command in the #apply channel.")
    await channel.send(embed=embed)

@bot.command()
async def apply(ctx):
    if isinstance(ctx.channel, discord.DMChannel) or ctx.channel.name != 'apply':
        embed = discord.Embed(description="❗ Please use this command in the #apply channel.", color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=30)
        return

    await ctx.message.delete()
    dm_channel = await ctx.author.create_dm()

    def check(m): return m.author == ctx.author and m.channel == dm_channel

    try:
        # Ask for Steam profile
        embed = discord.Embed(description="🔗 Please provide your Steam profile link (must be a valid URL).", color=discord.Color.blue())
        await dm_channel.send(embed=embed)

        while True:
            steam_msg = await bot.wait_for('message', check=check, timeout=60.0)
            steam_link = steam_msg.content.strip()

            if STEAM_PROFILE_REGEX.match(steam_link):
                break
            await dm_channel.send("❗ That doesn't look like a valid Steam profile link. Try again.")

        # Ask for hours played
        embed = discord.Embed(description="🕒 How many hours have you played Project Zomboid?", color=discord.Color.blue())
        await dm_channel.send(embed=embed)

        hours_msg = await bot.wait_for('message', check=check, timeout=60.0)
        hours_played = hours_msg.content.strip()

        # Ask for rule confirmation
        embed = discord.Embed(description=f"**Steam Profile:** {steam_link}\n**Zomboid Hours:** {hours_played}\n\nReply with `I confirm` to acknowledge you've read the rules.", color=discord.Color.blue())
        await dm_channel.send(embed=embed)

        confirm_msg = await bot.wait_for('message', check=check, timeout=60.0)

        if confirm_msg.content.lower() != 'i confirm':
            await dm_channel.send(embed=discord.Embed(description="❌ You didn't confirm reading the rules. Application cancelled.", color=discord.Color.red()))
            return

        # Send application to #apply channel
        apply_channel = discord.utils.get(ctx.guild.text_channels, name='apply')
        if not apply_channel:
            await dm_channel.send(embed=discord.Embed(description="⚠️ Could not find #apply channel.", color=discord.Color.red()))
            return

        embed = discord.Embed(description=f"📝 **Application submitted by {ctx.author.mention}**\n\n**Steam:** {steam_link}\n**Hours:** {hours_played}\n\nStaff may approve or decline below.", color=discord.Color.green())
        view = ApproveDeclineView(applicant_id=ctx.author.id, steam_link=steam_link)
        await apply_channel.send(embed=embed, view=view)

        await dm_channel.send(embed=discord.Embed(description="✅ Application submitted! You'll be notified of the decision in the #apply channel.", color=discord.Color.green()))

    except asyncio.TimeoutError:
        await dm_channel.send(embed=discord.Embed(description="⏱️ You took too long to respond. Application timed out.", color=discord.Color.red()))

bot.run(DISCORD_TOKEN)
