import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import re

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Replace with your bot token
DISCORD_TOKEN = 'YOUR_DISCORD_TOKEN'

STEAM_PROFILE_REGEX = re.compile(r'https?://steamcommunity\.com/(id|profiles)/[a-zA-Z0-9_-]+/?')

class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve_button")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.name.lower() in ["staff", "headstaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff or headstaff can approve applications.", ephemeral=True)
            return
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.send_message(f"✅ Application for {user.mention} **approved** by {interaction.user.mention}!")
        except discord.NotFound:
            await interaction.response.send_message("⚠️ User not found.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.name.lower() in ["staff", "headstaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff or headstaff can decline applications.", ephemeral=True)
            return
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.send_message(f"❌ Application for {user.mention} **declined** by {interaction.user.mention}.")
        except discord.NotFound:
            await interaction.response.send_message("⚠️ User not found.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    # Register persistent view once
    bot.add_view(ApproveDeclineView(applicant_id=0))

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
    if ctx.channel.name != 'apply':
        embed = discord.Embed(description="❗ Please use this command in the #apply channel.", color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=30)
        return

    messages_to_delete = [ctx.message]

    def check(m): return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Ask for Steam profile
        embed = discord.Embed(description="🔗 Please provide your Steam profile link (must be a valid URL).", color=discord.Color.blue())
        response = await ctx.send(embed=embed)
        messages_to_delete.append(response)

        while True:
            steam_msg = await bot.wait_for('message', check=check, timeout=60.0)
            messages_to_delete.append(steam_msg)
            steam_link = steam_msg.content.strip()

            if STEAM_PROFILE_REGEX.match(steam_link):
                break
            else:
                warning = await ctx.send("❗ That doesn't look like a valid Steam profile link. Try again.")
                messages_to_delete.append(warning)

        # Ask for hours played
        embed = discord.Embed(description="🕒 How many hours have you played Project Zomboid?", color=discord.Color.blue())
        response = await ctx.send(embed=embed)
        messages_to_delete.append(response)

        hours_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(hours_msg)
        hours_played = hours_msg.content.strip()

        # Ask for rule confirmation
        embed = discord.Embed(description=f"**Steam Profile:** {steam_link}\n**Zomboid Hours:** {hours_played}\n\nReply with `I confirm` to acknowledge you've read the rules.", color=discord.Color.blue())
        response = await ctx.send(embed=embed)
        messages_to_delete.append(response)

        confirm_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(confirm_msg)

        if confirm_msg.content.lower() != 'i confirm':
            error = discord.Embed(description="❌ You didn't confirm reading the rules. Application cancelled.", color=discord.Color.red())
            cancel_msg = await ctx.send(embed=error)
            messages_to_delete.append(cancel_msg)
            await asyncio.sleep(20)
            for msg in messages_to_delete:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
            return

        # Final embed with buttons
        embed = discord.Embed(description=f"📝 **Application submitted by {ctx.author.mention}**\n\n**Steam:** {steam_link}\n**Hours:** {hours_played}\n\nStaff may approve or decline below.", color=discord.Color.green())
        view = ApproveDeclineView(applicant_id=ctx.author.id)
        approval_msg = await ctx.send(embed=embed, view=view)
        messages_to_delete.append(approval_msg)

        await asyncio.sleep(300)
        for msg in messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

    except asyncio.TimeoutError:
        timeout = discord.Embed(description="⏱️ You took too long to respond. Application timed out.", color=discord.Color.red())
        timeout_msg = await ctx.send(embed=timeout)
        messages_to_delete.append(timeout_msg)
        await asyncio.sleep(30)
        for msg in messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

bot.run(DISCORD_TOKEN)
