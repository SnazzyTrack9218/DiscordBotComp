import discord
from discord.ext import commands
import asyncio
import requests
from datetime import datetime

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Replace with your Discord bot token
DISCORD_TOKEN = 'YOUR_DISCORD_TOKEN'
# Replace with your Steam API key
STEAM_API_KEY = 'YOUR_STEAM_API_KEY'

class ApproveButton(discord.ui.View):
    def __init__(self, applicant_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has Staff or HeadStaff role
        if not any(role.name in ["Staff", "HeadStaff"] for role in interaction.user.roles):
            await interaction.response.send_message("Only Staff or HeadStaff can approve applications.", ephemeral=True)
            return

        # Fetch applicant
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
    # Wait for user to input Steam profile link via !apply
    # Welcome message will be handled in !apply to ensure we have the Steam link
    pass

@bot.command()
async def apply(ctx):
    await ctx.send("Please provide your Steam profile link.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        # Get Steam profile link
        steam_msg = await bot.wait_for('message', check=check, timeout=60.0)
        steam_link = steam_msg.content

        # Fetch Steam account creation date
        steam_id = steam_link.split('/')[-2] if steam_link.endswith('/') else steam_link.split('/')[-1]
        url = f'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={STEAM_API_KEY}&steamids={steam_id}'
        response = requests.get(url)
        
        if response.status_code != 200:
            await ctx.send("Error fetching Steam data. Please check your Steam profile link.")
            return

        data = response.json()
        player = data.get('response', {}).get('players', [{}])[0]
        creation_time = player.get('timecreated')
        
        if creation_time:
            creation_date = datetime.fromtimestamp(creation_time)
            account_age = (datetime.now() - creation_date).days // 365
        else:
            account_age = "Unknown"

        # Get hours played
        await ctx.send("How many hours have you played in the game?")
        hours_msg = await bot.wait_for('message', check=check, timeout=60.0)
        hours_played = hours_msg.content

        # Confirm rules
        await ctx.send(f"Steam Profile: {steam_link}\nHours in game: {hours_played}\nPlease confirm you have read the rules by replying 'I confirm'.")
        confirm_msg = await bot.wait_for('message', check=check, timeout=60.0)

        if confirm_msg.content.lower() == 'i confirm':
            # Send welcome message with Steam profile and account age
            channel = ctx.channel
            await channel.send(f"Welcome {ctx.author.mention}!\nSteam Profile: {steam_link}\nAccount Age: {account_age} years")
            # Send application for approval
            view = ApproveButton(ctx.author.id)
            await ctx.send(f"Application submitted for {ctx.author.mention}! Staff or HeadStaff, please approve using the button below.", view=view)
        else:
            await ctx.send("You did not confirm reading the rules.")
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond.")

bot.run(DISCORD_TOKEN)
