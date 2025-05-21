Project Zomboid Discord Application Bot
A Discord bot for managing Project Zomboid server applications with advanced features and customization options.
Features

Full Application System: Process server join applications with Steam profile verification
Customizable Questions: Add your own questions to the application process
Role Management: Automatically assign roles to approved members
Admin Controls: Comprehensive configuration options for server admins
Application History: Track pending, approved, and declined applications
Cooldown System: Prevent spam applications with configurable cooldowns
User-Friendly: Guided application process through direct messages
Staff Workflow: Simple approve/decline interface with reason tracking
Secure: Environment-based token storage and permission controls

Installation

Clone this repository:
git clone https://github.com/yourusername/project-zomboid-application-bot.git
cd project-zomboid-application-bot

Install the required packages:
pip install discord.py python-dotenv

Set up your environment file:

Copy the .env.example file to .env
Add your Discord bot token to the .env file:
DISCORD_TOKEN=your_token_here



Run the bot:
python bot.py


Bot Setup

Create a Discord Application:

Go to the Discord Developer Portal
Create a new application and add a bot
Enable necessary intents (Message Content, Server Members)
Get your bot token for the .env file


Invite the Bot to Your Server:

Generate an invite link with appropriate permissions
Required permissions: Manage Roles, Read Messages, Send Messages, Read Message History, etc.


Configure the Bot:

Set up your staff roles: !config staff_roles staff,admin,moderator
Set your member role: !config member_role member
Set your application channel: !config apply_channel apply
Add custom questions (optional): !add_question How often do you play Project Zomboid?



Commands
Public Commands

!apply - Start the application process
!help - Show available commands

Staff Commands

!applications [status] - View applications (pending/approved/declined/all)
!application_details <user> - View detailed application info for a user

Admin Commands

!config [setting] [value] - View or change bot configuration
!add_question <question> - Add a custom application question
!remove_question <index> - Remove a custom application question
!list_questions - List all custom application questions
!clear_applications <status> - Clear applications with the specified status

Configuration Options
SettingDescriptionDefaultstaff_rolesRoles that can process applicationsstaff,headstaff,admin,moderatormember_roleRole assigned to approved membersmemberapply_channelChannel for application commandsapplywelcome_channelChannel for welcome messagesNone (uses system channel)min_hoursMinimum required hours (not enforced)0application_cooldownTime before rejected users can reapply86400 (24 hours)custom_questionsAdditional questions to ask[]
Troubleshooting

Bot Not Responding: Check if your bot token is correct and if the bot has appropriate permissions
Can't Assign Roles: Ensure the bot's role is higher than the roles it needs to assign
Missing Messages: Make sure the bot has permission to send messages in the necessary channels
Application Issues: Check the log file for detailed error information

License
This project is licensed under the MIT License - see the LICENSE file for details.
