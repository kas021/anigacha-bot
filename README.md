# Discord Gacha Bot

A Discord bot inspired by gacha/claim-style waifu bots. Roll characters, claim them, build your collection, and compete with friends!

This bot uses an SQLite database to track users, characters, inventories, and cooldowns. Characters are automatically fetched from AniList's API with images and metadata.

## Features

- **Roll System**: Roll random characters with `$w` / `$roll` (limited rolls per hour)
- **Claim System**: Claim your rolled characters within a time window using `$claim`
- **Currency System**: Earn cash through daily rewards and claiming characters
- **Daily Rewards**: Get free cash every ~20 hours with `$daily`
- **Inventory Tracking**: View your collection with `$inventory`
- **Owner Commands**: Populate the database with AniList characters (`$populate`) or manually add custom characters (`$addcard`)
- **Cooldown Management**: Built-in rate limiting and cooldowns for a fair gameplay experience

## Commands

| Command             | Access     | Description                                                                                   |
| ------------------- | ---------- | --------------------------------------------------------------------------------------------- |
| `$info`             | everyone   | Show game rules and how the bot works.                                                        |
| `$w` / `$roll`      | everyone   | Roll a random character. You get a limited number of rolls per hour.                          |
| `$claim`            | everyone   | Claim the last character you rolled in that channel, if you're still within the claim window. |
| `$daily`            | everyone   | Get free in-game currency once per cooldown period.                                           |
| `$balance`          | everyone   | Show your current currency.                                                                   |
| `$inventory [user]` | everyone   | Show your collection, or another user's collection.                                           |
| `$rolls`            | everyone   | Refresh your roll count after a "vote-style" reset. Has its own cooldown.                     |
| `$vote`             | everyone   | Gives a link / message telling users how to "support the bot".                                |
| `$populate <n>`     | owner only | Pull up to `n` characters from AniList and insert them into the database.                     |
| `$addcard ...`      | owner only | Manually add a specific character (name, series, rarity, image, value) into the database.     |

### Important Cooldown Rules

- **Rolls**: You only get 10 rolls per hour (automatically resets)
- **Claim Cooldown**: Global 3-hour cooldown between successful claims per user
- **Claim Window**: You must claim within 120 seconds after rolling or the character expires
- **Daily Cooldown**: ~20 hours between daily rewards
- **Roll Reset**: The `$rolls` command has a ~12 hour cooldown

## Requirements

- Python 3.10 or higher
- Required libraries:
  - `discord.py` >= 2.0.0
  - `aiohttp` >= 3.8.0
  - `python-dotenv` >= 0.19.0

## Installation

1. Clone this repository:
   ```bash
   git clone <repo-url>
   cd <repo-directory>
   ```

2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   ```
   Then activate it:
   - **Windows**: `venv\Scripts\activate`
   - **Linux/Mac**: `source venv/bin/activate`

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Environment Setup

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your values:
   - `DISCORD_BOT_TOKEN`: Your bot token from the [Discord Developer Portal](https://discord.com/developers/applications)
     - Go to your application → Bot → Copy the token
   - `GUILD_ID`: (Optional) Your server/guild ID. Enable Developer Mode in Discord, right-click your server → Server Settings → Copy ID
   - `BOT_OWNER_ID`: Your Discord user ID (enables owner commands). Right-click yourself → Copy ID

## Running the Bot

1. Start the bot:
   ```bash
   python mudae_clone_bot.py
   ```

2. Invite your bot to your server:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Select your bot → OAuth2 → URL Generator
   - Select the `bot` scope and enable the "MESSAGE CONTENT INTENT"
   - Copy the generated URL and open it in your browser
   - Select your server and authorize

3. **IMPORTANT**: Enable "MESSAGE CONTENT INTENT" in your bot settings:
   - Discord Developer Portal → Your Bot → Privileged Gateway Intents
   - Toggle on "MESSAGE CONTENT INTENT"
   - Save changes

4. Populate the database (in your Discord server):
   ```
   $populate 500
   ```
   This fetches characters from AniList and may take a few minutes.

## Data / Persistence

The bot stores all data in a local SQLite file (`anime_card_bot.db`):

- **users**: Cash balances, cooldowns, roll counts, timers
- **cards**: Character information (name, series, age, image URL, rarity, value)
- **inventory**: User-card ownership relationships

**Warning**: Deleting the database file will reset all user progress, collections, and data.

## Security Notes

- **NEVER commit a real `.env` file** to version control. The `.env.example` file is provided as a template.
- **NEVER hardcode** IDs or tokens in the source code before pushing to GitHub
- The `BOT_OWNER_ID` has full control over the database (can add/remove characters). Do not share this ID casually
- The bot makes external API calls to AniList when using `$populate`. Be mindful of rate limits

## Troubleshooting

**"No cards in the database yet"**
- Run `$populate 500` to add characters to the database

**Bot not responding to commands**
- Verify the bot token is correct in your `.env` file
- Ensure MESSAGE CONTENT INTENT is enabled in the Developer Portal
- Check that the bot has permissions in the channel

**"You are not authorized" error**
- Verify your `BOT_OWNER_ID` is set correctly in `.env`
- Make sure it's YOUR user ID, not your bot's ID

## Disclaimer

This is a fan-made, educational project inspired by gacha/claim-style Discord bots. It is not affiliated with any existing monetized bot, anime licensor, or official Discord service.

## License

This project is open source and available for educational purposes. Use responsibly.
