# Project Zomboid Discord Application Bot

A Discord bot for managing Project Zomboid server applications with a streamlined application process, staff workflow, and role management.

## Features

- **Application System**: Users apply to join the server via `!apply`, providing a Steam profile link and hours played.
- **Staff Workflow**: Staff with `staff` or `headstaff` roles can approve or decline applications using buttons or the `!approve` command.
- **Role Management**: Automatically assigns the `member` role to approved users.
- **Application Tracking**: View pending, approved, or declined applications with `!applications`.
- **Cooldown System**: Configurable cooldown prevents reapplication after a decline (default: 24 hours).
- **Clear Applications**: Staff can clear applications by status (`!clear`) to manage application history.
- **Secure Configuration**: Uses a `.env` file for the Discord bot token and `config.json` for settings.
- **User-Friendly**: Guided application process via direct messages with error handling.
- **Logging**: Errors and events are logged to `bot.log` for debugging.

*Note*: Features like customizable questions (`!add_question`, `!remove_question`) and detailed application views (`!application_details`) are planned but not yet implemented.

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/SnazzyTrack9218/DiscordBotComp.git
   cd DiscordBotComp
