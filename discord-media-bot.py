import discord
from discord.ext import commands
import json
import os
import aiohttp
import asyncio
from typing import Optional, List, Dict, Any
import logging
import io
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration file path
CONFIG_FILE = "bot_config.json"

class MediaCopyBot(commands.Bot):
    def __init__(self):
        # Set up intents - required for discord.py v2.x
        intents = discord.Intents.default()
        intents.message_content = True  # Required for reading message content
        intents.guilds = True  # Required for guild operations
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        # Load configuration
        self.config = self.load_config()
        
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("Invalid JSON in config file, creating new config")
        
        # Default configuration
        default_config = {
            "monitored_channels": {},  # guild_id: [channel_ids]
            "media_channels": {},      # guild_id: channel_id
            "include_author": {},      # guild_id: boolean
            "monitor_all": {}          # guild_id: boolean
        }
        
        self.save_config(default_config)
        return default_config
    
    def save_config(self, config: Dict[str, Any] = None):
        """Save configuration to JSON file"""
        if config is None:
            config = self.config
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    
    async def on_ready(self):
        """Bot ready event"""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Initialize config for all guilds
        for guild in self.guilds:
            guild_id = str(guild.id)
            if guild_id not in self.config["monitored_channels"]:
                self.config["monitored_channels"][guild_id] = []
            if guild_id not in self.config["media_channels"]:
                self.config["media_channels"][guild_id] = None
            if guild_id not in self.config["include_author"]:
                self.config["include_author"][guild_id] = True
            if guild_id not in self.config["monitor_all"]:
                self.config["monitor_all"][guild_id] = False
        
        self.save_config()
        
        # Set bot status
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for media content"
            )
        )
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore bot messages
        if message.author.bot:
            return
            
        # Process commands first
        await self.process_commands(message)
        
        # Check if message should be copied
        if await self.should_copy_message(message):
            await self.copy_media_message(message)
    
    async def should_copy_message(self, message) -> bool:
        """Check if message contains media and is from a monitored channel"""
        if not message.guild:
            return False
            
        guild_id = str(message.guild.id)
        
        # Check if guild is configured
        if guild_id not in self.config["monitored_channels"]:
            return False
            
        # Check if media channel is set
        media_channel_id = self.config["media_channels"].get(guild_id)
        if not media_channel_id:
            return False
            
        # Don't copy from the media channel itself
        if message.channel.id == media_channel_id:
            return False
            
        # Check monitoring mode
        if self.config["monitor_all"].get(guild_id, False):
            # Monitor all channels except media channel
            pass
        else:
            # Check if channel is in monitored list
            if message.channel.id not in self.config["monitored_channels"][guild_id]:
                return False
            
        # Check if message has media content
        return self.has_media_content(message)
    
    def has_media_content(self, message) -> bool:
        """
        Check if message contains embedded media or attachments
        This includes:
        - Directly uploaded files (images, videos, GIFs)
        - Embedded media from URLs (when Discord shows a preview)
        """
        # Check for direct uploads (attachments)
        if message.attachments:
            for attachment in message.attachments:
                # Check if attachment is image/video/gif
                if any(attachment.filename.lower().endswith(ext) for ext in 
                       ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', 
                        '.mov', '.avi', '.webm', '.bmp', '.tiff']):
                    return True
        
        # Check for embedded media (from URLs)
        if message.embeds:
            for embed in message.embeds:
                # Check if embed has image, video, or thumbnail
                if (embed.image or embed.video or embed.thumbnail or 
                    (embed.type in ['image', 'video', 'gifv', 'article', 'link'])):
                    # Additional check for article/link embeds with images
                    if embed.type in ['article', 'link'] and (embed.image or embed.thumbnail):
                        return True
                    elif embed.type in ['image', 'video', 'gifv']:
                        return True
        
        return False
    
    async def copy_media_message(self, message):
        """Copy message with media to the designated media channel"""
        try:
            guild_id = str(message.guild.id)
            media_channel_id = self.config["media_channels"][guild_id]
            media_channel = self.get_channel(media_channel_id)
            
            if not media_channel:
                logger.warning(f"Media channel {media_channel_id} not found")
                return
            
            # Check bot permissions in media channel
            permissions = media_channel.permissions_for(message.guild.me)
            if not permissions.send_messages or not permissions.attach_files:
                logger.warning(f"Missing permissions in {media_channel.name}")
                return
            
            # Rate limit check - avoid spamming
            await asyncio.sleep(0.5)
            
            # Create new embed for the copied message
            include_author = self.config["include_author"][guild_id]
            
            # Handle direct file uploads
            files = []
            if message.attachments:
                for attachment in message.attachments:
                    # Check file size (Discord bot limit is 8MB)
                    if attachment.size <= 8 * 1024 * 1024:
                        try:
                            # Download attachment
                            async with aiohttp.ClientSession() as session:
                                async with session.get(attachment.url) as resp:
                                    if resp.status == 200:
                                        file_data = await resp.read()
                                        files.append(
                                            discord.File(
                                                io.BytesIO(file_data),
                                                filename=attachment.filename,
                                                spoiler=attachment.is_spoiler()
                                            )
                                        )
                        except Exception as e:
                            logger.error(f"Error downloading attachment: {e}")
            
            # Create info embed
            embed = discord.Embed(
                description=message.content[:1024] if message.content else None,
                color=0x00ff00,
                timestamp=message.created_at
            )
            
            if include_author:
                embed.set_author(
                    name=f"{message.author.display_name}",
                    icon_url=message.author.display_avatar.url
                )
            
            embed.add_field(
                name="Source",
                value=f"#{message.channel.name}",
                inline=True
            )
            
            embed.add_field(
                name="Jump to Original",
                value=f"[Click here]({message.jump_url})",
                inline=True
            )
            
            # Prepare embeds to send
            embeds_to_send = [embed]
            
            # Copy original embeds (for URL embeds with media)
            if message.embeds:
                for i, original_embed in enumerate(message.embeds[:9]):  # Max 10 embeds total
                    try:
                        # Only copy embeds that have media
                        if (original_embed.image or original_embed.video or 
                            original_embed.thumbnail or original_embed.type in ['image', 'video', 'gifv']):
                            new_embed = discord.Embed.from_dict(original_embed.to_dict())
                            embeds_to_send.append(new_embed)
                    except Exception as e:
                        logger.warning(f"Could not copy embed: {e}")
            
            # Send the copied message
            await media_channel.send(
                embeds=embeds_to_send,
                files=files
            )
            
            logger.info(f"Copied media from #{message.channel.name} to #{media_channel.name}")
            
        except discord.HTTPException as e:
            logger.error(f"Discord API error: {e}")
        except Exception as e:
            logger.error(f"Error copying message: {e}")

# Initialize bot
bot = MediaCopyBot()

# Command: Set up media channel
@bot.hybrid_command(name="setup", description="Set the media channel for this server")
@commands.has_permissions(manage_channels=True)
async def setup_media_channel(ctx, channel: discord.TextChannel):
    """Set up the media channel for this server"""
    guild_id = str(ctx.guild.id)
    bot.config["media_channels"][guild_id] = channel.id
    bot.save_config()
    
    embed = discord.Embed(
        title="✅ Media Channel Set",
        description=f"Media will be copied to {channel.mention}",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

# Command group: Monitor
@bot.hybrid_group(name="monitor", description="Manage channel monitoring")
@commands.has_permissions(manage_channels=True)
async def monitor_group(ctx):
    """Parent group for monitoring commands"""
    if ctx.invoked_subcommand is None:
        await ctx.send("Use `/monitor help` for available commands")

@monitor_group.command(name="add", description="Add a channel to monitor")
async def monitor_add(ctx, channel: discord.TextChannel):
    """Add a channel to monitor for media"""
    guild_id = str(ctx.guild.id)
    
    if guild_id not in bot.config["monitored_channels"]:
        bot.config["monitored_channels"][guild_id] = []
    
    if channel.id not in bot.config["monitored_channels"][guild_id]:
        bot.config["monitored_channels"][guild_id].append(channel.id)
        bot.save_config()
        
        embed = discord.Embed(
            title="✅ Channel Added",
            description=f"Now monitoring {channel.mention} for media",
            color=0x00ff00
        )
    else:
        embed = discord.Embed(
            title="ℹ️ Already Monitoring",
            description=f"Already monitoring {channel.mention}",
            color=0xffff00
        )
    
    await ctx.send(embed=embed)

@monitor_group.command(name="remove", description="Remove a channel from monitoring")
async def monitor_remove(ctx, channel: discord.TextChannel):
    """Remove a channel from monitoring"""
    guild_id = str(ctx.guild.id)
    
    if (guild_id in bot.config["monitored_channels"] and 
        channel.id in bot.config["monitored_channels"][guild_id]):
        
        bot.config["monitored_channels"][guild_id].remove(channel.id)
        bot.save_config()
        
        embed = discord.Embed(
            title="✅ Channel Removed",
            description=f"No longer monitoring {channel.mention}",
            color=0x00ff00
        )
    else:
        embed = discord.Embed(
            title="ℹ️ Not Monitoring",
            description=f"Was not monitoring {channel.mention}",
            color=0xffff00
        )
    
    await ctx.send(embed=embed)

@monitor_group.command(name="all", description="Toggle monitoring all channels")
async def monitor_all(ctx, enabled: bool = None):
    """Toggle monitoring all channels except media channel"""
    guild_id = str(ctx.guild.id)
    
    if enabled is None:
        current = bot.config["monitor_all"].get(guild_id, False)
        enabled = not current
    
    bot.config["monitor_all"][guild_id] = enabled
    bot.save_config()
    
    if enabled:
        bot.config["monitored_channels"][guild_id] = []
        bot.save_config()
        status = "🌐 Now monitoring **all channels** (except destination)"
    else:
        status = "📍 Switched to monitoring **specific channels only**"
    
    embed = discord.Embed(
        title="✅ Monitor Mode Updated",
        description=status,
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@monitor_group.command(name="list", description="List all monitored channels")
async def monitor_list(ctx):
    """Show current monitoring configuration"""
    guild_id = str(ctx.guild.id)
    
    embed = discord.Embed(
        title="📺 Media Monitoring Status",
        color=0x0099ff
    )
    
    # Media channel
    media_channel_id = bot.config["media_channels"].get(guild_id)
    if media_channel_id:
        media_channel = bot.get_channel(media_channel_id)
        embed.add_field(
            name="📸 Media Channel",
            value=media_channel.mention if media_channel else "Channel not found",
            inline=False
        )
    else:
        embed.add_field(
            name="📸 Media Channel",
            value="Not configured (use `/setup`)",
            inline=False
        )
    
    # Monitor mode
    if bot.config["monitor_all"].get(guild_id, False):
        embed.add_field(
            name="🌐 Monitor Mode",
            value="All channels (except destination)",
            inline=False
        )
    else:
        # Monitored channels
        monitored = bot.config["monitored_channels"].get(guild_id, [])
        if monitored:
            channels = []
            for channel_id in monitored:
                channel = bot.get_channel(channel_id)
                if channel:
                    channels.append(channel.mention)
            
            embed.add_field(
                name="📍 Monitored Channels",
                value="\n".join(channels) if channels else "No valid channels",
                inline=False
            )
        else:
            embed.add_field(
                name="📍 Monitored Channels",
                value="None (use `/monitor add`)",
                inline=False
            )
    
    # Author attribution
    include_author = bot.config["include_author"].get(guild_id, True)
    embed.add_field(
        name="👤 Author Attribution",
        value="Enabled" if include_author else "Disabled",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.hybrid_command(name="toggle_author", description="Toggle author attribution")
@commands.has_permissions(manage_channels=True)
async def toggle_author_attribution(ctx):
    """Toggle author attribution in copied messages"""
    guild_id = str(ctx.guild.id)
    
    current = bot.config["include_author"].get(guild_id, True)
    bot.config["include_author"][guild_id] = not current
    bot.save_config()
    
    status = "enabled" if not current else "disabled"
    embed = discord.Embed(
        title="✅ Author Attribution Updated",
        description=f"Author attribution is now **{status}**",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="help", description="Show bot commands")
async def help_command(ctx):
    """Show help information"""
    embed = discord.Embed(
        title="📸 Media Copy Bot Help",
        description="This bot copies media content (images, videos, GIFs) to a designated channel.",
        color=0x0099ff
    )
    
    embed.add_field(
        name="Setup Commands",
        value=(
            "`/setup #channel` - Set the media destination channel\n"
            "`/monitor add #channel` - Add a channel to monitor\n"
            "`/monitor remove #channel` - Stop monitoring a channel\n"
            "`/monitor all` - Toggle monitoring all channels\n"
            "`/monitor list` - Show current configuration"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Other Commands",
        value=(
            "`/toggle_author` - Toggle showing who posted the media\n"
            "`/help` - Show this help message"
        ),
        inline=False
    )
    
    embed.add_field(
        name="What gets copied?",
        value=(
            "• Directly uploaded images/videos/GIFs\n"
            "• Embedded media from URLs (previews)\n"
            "• Does NOT copy plain text links"
        ),
        inline=False
    )
    
    embed.set_footer(text="All commands require 'Manage Channels' permission")
    
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permission Error",
            description="You need 'Manage Channels' permission to use this command",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.ChannelNotFound):
        embed = discord.Embed(
            title="❌ Channel Not Found",
            description="Please mention a valid channel",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CommandNotFound):
        # Ignore command not found errors
        pass
    else:
        logger.error(f"Unhandled error: {error}")

if __name__ == "__main__":
    # Get token from environment variable
    TOKEN = os.getenv("DISCORD_TOKEN")
    
    if not TOKEN:
        print("❌ Please set DISCORD_TOKEN environment variable")
        print("Create a .env file with: DISCORD_TOKEN=your_bot_token_here")
        exit(1)
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid bot token! Please check your DISCORD_TOKEN")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")