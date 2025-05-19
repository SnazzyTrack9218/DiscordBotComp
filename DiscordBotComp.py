import discord
from discord.ext import commands
import asyncio
from datetime import datetime

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Replace with your Discord bot token
DISCORD_TOKEN = 'YOUR_DISCORD_TOKEN'

class ApproveButton(discord.ui.View):
    def __init__(self, applicant_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.name in ["Staff", "HeadStaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only Staff or HeadStaff can approve applications.", ephemeral=True)
            return
        try:
            user = await bot.fetch_user(self.applicant_id)
            await interaction.response.send_message(f"Application for {user.mention} approved by {interaction.user.mention}!")
        except discord.NotFound:
            await interaction.response.send_message("User not found.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel or (await member.guild.text_channels())[0]
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
        await ctx.send("Please use this command in the #apply channel.", delete_after=300)
        return

    messages_to_delete = [ctx.message]
    response = await ctx.send("Please provide your Steam profile link.")
    messages_to_delete.append(response)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        steam_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(steam_msg)
        steam_link = steam_msg.content

        response = await ctx.send("How many hours have you played in Project Zomboid?")
        messages_to_delete.append(response)
        hours_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(hours_msg)
        hours_played = hours_msg.content

        response = await ctx.send(f"Steam Profile: {steam_link}\nProject Zomboid Hours: {hours_played}\nPlease confirm you have read the rules by replying 'I confirm'.")
        messages_to_delete.append(response)
        confirm_msg = await bot.wait_for('message', check=check, timeout=60.0)
        messages_to_delete.append(confirm_msg)

        if confirm_msg.content.lower() == 'i confirm':
            view = ApproveButton(ctx.author.id)
            approval_msg = await ctx.send(f"Application submitted for {ctx.author.mention}! Steam Profile: {steam_link}, Project Zomboid Hours: {hours_played}. Staff or HeadStaff, please approve using the button below.", view=view)
            messages_to_delete.append(approval_msg)
            await asyncio.sleep(300)  # Wait 5 minutes
            for msg in messages_to_delete:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
        else:
            response = await ctx.send("You did not confirm reading the rules.")
            messages_to_delete.append(response)
            await asyncio.sleep(300)  # Wait 5 minutes
            for msg in messages_to_delete:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass
    except asyncio.TimeoutError:
        response = await ctx.send("You took too long to respond.")
        messages_to_delete.append(response)
        await asyncio.sleep(300)  # Wait 5 minutes
        for msg in messages_to_delete:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

bot.run(DISCORD_TOKEN)
