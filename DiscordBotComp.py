import discord
from discord.ext import commands
import asyncio
import re
from datetime import datetime

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

DISCORD_TOKEN = 'YOUR_DISCORD_TOKEN'  # Replace with your bot token


def is_valid_steam_link(link):
    return bool(re.match(r'^https:\/\/steamcommunity\.com\/(id|profiles)\/[a-zA-Z0-9_]+$', link))


class ApproveDeclineView(discord.ui.View):
    def __init__(self, applicant_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.name in ["staff", "headstaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff or headstaff can approve applications.", ephemeral=True)
            return
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.send_message(
                f"✅ Application for {user.mention} approved by {interaction.user.mention}!")
        except discord.NotFound:
            await interaction.response.send_message("User not found.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.name in ["staff", "headstaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only staff or headstaff can decline applications.", ephemeral=True)
            return
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.send_message(
                f"❌ Application for {user.mention} declined by {interaction.user.mention}.")
        except discord.NotFound:
            await interaction.response.send_message("User not found.", ephemeral=True)


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    bot.add_view(ApproveDeclineView(applicant_id=0))  # Needed for persistent buttons


@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel or (await member.guild.fetch_channels())[0]
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
        embed = discord.Embed(description="Please use this command in the #apply channel.",
                              color=discord.Color.red())
        await ctx.send(embed=embed, delete_after=300)
        return

    messages_to_delete = [ctx.message]
    def check(m): return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Ask for Steam link with 3 chances
        for attempt in range(3):
            embed = discord.Embed(description="Please provide your **Steam profile link**:",
                                  color=discord.Color.blue())
            prompt = await ctx.send(embed=embed)
            messages_to_delete.append(prompt)
            steam_msg = await bot.wait_for('message', check=check, timeout=60.0)
            messages_to_delete.append(steam_msg)

            if is_valid_steam_link(steam_msg.content.strip()):
                steam_link = steam_msg.content.strip()
                break
            else:
                error = await ctx.send("❌ Invalid Steam link. Format must be like: `https://steamcommunity.com/id/yourname`", delete_after=10)
                messages_to_delete.append(error)
        else:
            fail = await ctx.send("❌ Too many invalid attempts. Please try again later.", delete_after=10)
            messages_to_delete.append(fail)
            await asyncio.sleep(10)
            for msg in messages_to_delete:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
            return

        # Ask for PZ hours
        embed = discord.Embed(description="How many **Project Zomboid** hours do you have?",
                              color=discord.Color.blue())
        prompt = await ctx.send(embed=embed)
        messages_to_delete.append(prompt)
        hours_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(hours_msg)
        hours_played = hours_msg.content.strip()

        # Confirm reading rules
        embed = discord.Embed(description="Please confirm you’ve read the rules by typing `I confirm`.",
                              color=discord.Color.blue())
        prompt = await ctx.send(embed=embed)
        messages_to_delete.append(prompt)
        confirm_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(confirm_msg)

        if confirm_msg.content.lower().strip() != "i confirm":
            error = await ctx.send("❌ You didn’t confirm reading the rules. Application canceled.", delete_after=10)
            messages_to_delete.append(error)
            await asyncio.sleep(10)
            for msg in messages_to_delete:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
            return

        # Send application with Approve/Decline buttons
        embed = discord.Embed(
            description=f"📝 **Application submitted by {ctx.author.mention}**\n"
                        f"**Steam:** {steam_link}\n"
                        f"**Project Zomboid Hours:** {hours_played}\n"
                        f"Staff or headstaff, please use the buttons below.",
            color=discord.Color.green()
        )
        view = ApproveDeclineView(applicant_id=ctx.author.id)
        final_msg = await ctx.send(embed=embed, view=view)
        messages_to_delete.append(final_msg)

        await asyncio.sleep(300)  # Wait 5 min before cleanup
        for msg in messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

    except asyncio.TimeoutError:
        timeout_msg = await ctx.send("❌ You took too long to respond. Try again later.", delete_after=10)
        messages_to_delete.append(timeout_msg)
        await asyncio.sleep(10)
        for msg in messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass


bot.run(DISCORD_TOKEN)
