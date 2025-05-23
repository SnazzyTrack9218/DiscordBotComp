# Project Zomboid Discord Application Bot

A comprehensive Discord bot for managing Project Zomboid server applications with streamlined application processing, staff workflow, role management, and real-time server status monitoring.

![Bot Preview](https://via.placeholder.com/800x400?text=Project+Zomboid+Discord+Bot+Preview)

## Features

### Application System
- **User Applications**: Members apply via `!apply` with Steam profile and playtime
- **Guided Process**: Step-by-step application via DMs with validation
- **Cooldown System**: Configurable cooldown prevents reapplication after decline (default: 24 hours)

### Staff Tools
- **Approval System**: Staff approve/decline with buttons or `!approve` command
- **Application Review**: View applications by status (`!applications pending`)
- **Management**: Clear applications by status (`!clear declined`)

### Server Integration
- **Real-time Status**: `!status` shows current player count and online players
- **Auto Updates**: Channel message automatically updates with server status
- **Player List**: Displays currently online players (when <15 online)

### Role Management
- **Auto Role Assignment**: Approved users get member role automatically
- **Staff Permissions**: Configurable staff roles in config.json

### Configuration
- **Secure Setup**: `.env` for bot token, `config.json` for settings
- **Customizable**: Adjust cooldowns, required roles, and channels
- **Persistent Data**: Applications saved between bot restarts

## Installation

### Prerequisites
- Python 3.8+
- Discord bot token
- Project Zomboid server IP and query port

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/SnazzyTrack9218/DiscordBotComp.git
   cd DiscordBotComp
