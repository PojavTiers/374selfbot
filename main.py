import discord
import aiohttp
import json
import os
import re
import asyncio

# --- CONFIGURATION ---
CONFIG_FILE = 'config.json'
TOKENS_RAW = os.getenv('DISCORD_TOKEN')

if not TOKENS_RAW:
    raise ValueError("Please set the DISCORD_TOKEN environment variable.")

TOKENS = [t.strip().strip('"').strip("'") for t in TOKENS_RAW.split(',') if t.strip()]
if not TOKENS:
    raise ValueError("No valid tokens found in DISCORD_TOKEN environment variable.")

print(f"Found {len(TOKENS)} token(s). Starting clients...")

class SafeSelfBot(discord.Client):
    def __init__(self, token_index=0):
        super().__init__(self_bot=True)
        self.token_index = token_index
        self.config = self.load_config()
        self.user_id = None
        self.last_messages = {}
        self.auto_reacts = {}

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {"prefix": "-", "safe_mode": True}

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    async def on_ready(self):
        self.user_id = self.user.id
        print(f'[Client {self.token_index + 1}] Selfbot ready. User ID: {self.user_id}')
        print(f'[Client {self.token_index + 1}] Prefix: {self.config["prefix"]}')
        
        try:
            await self.change_presence(activity=None)
        except Exception:
            pass

    def bypass_text(self, text):
        if not self.config.get('safe_mode'):
            return text
        def replace_number(match):
            num = int(match.group())
            return "99" if num < 13 else match.group()
        text = re.sub(r'\b\d+\b', replace_number, text)
        text = re.sub(r'underage', 'overage', text, flags=re.IGNORECASE)
        text = re.sub(r'\bi\b', 'you', text, flags=re.IGNORECASE)
        text = re.sub(r'\bme\b', 'you', text, flags=re.IGNORECASE)
        return text

    async def on_message(self, message):
        if message.author.bot:
            return

        # Save other people's messages for the -mock command
        if message.author.id != self.user.id:
            channel_key = str(message.channel.id)
            user_key = str(message.author.id)
            if channel_key not in self.last_messages:
                self.last_messages[channel_key] = {}
            self.last_messages[channel_key][user_key] = message.content
            
            if str(message.author.id) in self.auto_reacts:
                for emoji in self.auto_reacts[str(message.author.id)]:
                    try:
                        await message.add_reaction(emoji)
                    except Exception:
                        pass
            return 

        # --- COMMAND HANDLING ---
        prefix = self.config.get('prefix', '-')
        if not message.content.startswith(prefix):
            return

        args = message.content[len(prefix):].strip().split()
        cmd = args[0].lower() if args else ""
        rest_args = args[1:]

        async def get_user_from_arg(arg):
            if not arg: return None
            if arg.startswith('<@') and arg.endswith('>'):
                uid = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                return await self.fetch_user(uid)
            elif arg.isdigit():
                return await self.fetch_user(int(arg))
            return None

        try:
            # --- PROFESSIONAL HELP MENU (NO EMBEDS) ---
            if cmd == 'help':
                help_text = (
                    "**374 SelfBot**\n"
                    "Advanced Discord Selfbot Platform\n"
                    f"**Prefix:** `{prefix}`\n\n"
                    "**[ UTILITY ]**\n"
                    f"`{prefix}ping` - Check latency\n"
                    f"`{prefix}setprefix <char>` - Change prefix\n"
                    f"`{prefix}avatar <@user>` - Get high-res avatar\n"
                    f"`{prefix}banner <@user>` - Get profile banner\n\n"
                    "**[ MODERATION ]**\n"
                    f"`{prefix}purge <1-100>` - Delete your recent messages\n"
                    f"`{prefix}dm <@user> <text>` - Send a direct message\n\n"
                    "**[ FUN & INTERACTIONS ]**\n"
                    f"`{prefix}react <@user> <emoji>` - Autoreact to a user\n"
                    f"`{prefix}clearreacts` - Stop autoreacting\n"
                    f"`{prefix}mock <@user>` - Mock their last message\n\n"
                    "**[ INFORMATION ]**\n"
                    f"`{prefix}userinfo <@user>` - Account details\n"
                    f"`{prefix}serverinfo` - Server stats\n\n"
                    "**[ RICH PRESENCE (RPC) ]**\n"
                    f"`{prefix}rpc <type> <text>` - Set custom status\n"
                    "*(Types: playing, watching, listening)*\n"
                    f"*Example: `{prefix}rpc playing 374 SelfBot`*"
                )
                await message.channel.send(help_text)

            # --- UTILITY ---
            elif cmd == 'setprefix':
                if rest_args:
                    self.config['prefix'] = rest_args[0]
                    self.save_config()
                    await message.channel.send(f"```Prefix changed to {self.config['prefix']}```")

            elif cmd == 'ping':
                await message.channel.send(f"```Ping: {round(self.latency * 1000, 2)}ms```")

            elif cmd == 'avatar':
                target = await get_user_from_arg(rest_args[0]) if rest_args else message.author
                if target:
                    await message.channel.send(target.avatar.url if target.avatar else "No avatar.")

            elif cmd == 'banner':
                target = await get_user_from_arg(rest_args[0]) if rest_args else message.author
                if target:
                    user = await self.fetch_user(target.id)
                    if user.banner:
                        await message.channel.send(user.banner.url)
                    else:
                        await message.channel.send("```User has no banner.```")

            # --- MODERATION ---
            elif cmd == 'purge':
                if not rest_args or not rest_args[0].isdigit():
                    await message.channel.send("```Usage: -purge <amount>```")
                    return
                amount = min(int(rest_args[0]), 100) 
                
                deleted = 0
                async for msg in message.channel.history(limit=200):
                    if msg.author.id == self.user.id and deleted < amount:
                        try:
                            await msg.delete()
                            deleted += 1
                        except Exception:
                            pass
                # Removed delete_after to fix library bug
                await message.channel.send(f"```Purged {deleted} messages.```")

            elif cmd == 'dm':
                target = await get_user_from_arg(rest_args[0]) if rest_args else None
                if not target or len(rest_args) < 2:
                    await message.channel.send("```Usage: -dm <@user> <message>```")
                    return
                text = " ".join(rest_args[1:])
                try:
                    await target.send(text)
                    await message.channel.send(f"```Sent DM to {target.name}```")
                except Exception:
                    await message.channel.send("```Failed to send DM.```")

            # --- FUN & INTERACTIONS ---
            elif cmd == 'mock':
                target_user = await get_user_from_arg(rest_args[0]) if rest_args else None
                if target_user:
                    last_msg = self.last_messages.get(str(message.channel.id), {}).get(str(target_user.id), "No recent messages.")
                    await message.channel.send(f"```\n{self.bypass_text(last_msg)}\n```")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -react <@user> <emoji>```")
                    return
                target_user = await get_user_from_arg(rest_args[0])
                emoji = rest_args[1]
                if target_user:
                    if target_user.id == self.user.id:
                        await message.channel.send("```You cannot autoreact to yourself. Pick someone else.```")
                        return
                    self.auto_reacts[str(target_user.id)] = [emoji]
                    await message.channel.send(f"```Reacting to {target_user.name} with {emoji}```")

            elif cmd == 'clearreacts':
                self.auto_reacts.clear()
                await message.channel.send("```All autoreacts cleared.```")

            # --- INFORMATION ---
            elif cmd == 'userinfo':
                target = await get_user_from_arg(rest_args[0]) if rest_args else message.author
                if target:
                    info_text = (
                        f"**User Info: {target.name}**\n"
                        f"ID: `{target.id}`\n"
                        f"Created: `{target.created_at.strftime('%Y-%m-%d')}`\n"
                    )
                    await message.channel.send(info_text)

            elif cmd == 'serverinfo':
                if not message.guild:
                    await message.channel.send("```Must be used in a server.```")
                    return
                server_text = (
                    f"**Server Info: {message.guild.name}**\n"
                    f"Members: `{message.guild.member_count}`\n"
                    f"Created: `{message.guild.created_at.strftime('%Y-%m-%d')}`"
                )
                await message.channel.send(server_text)

            # --- RPC ---
            elif cmd == 'rpc':
                if not rest_args or len(rest_args) < 2:
                    await message.channel.send("```Usage: -rpc <playing/watching/listening> <text>```")
                    return
                rtype = rest_args[0].lower()
                text = " ".join(rest_args[1:])
                
                if rtype == 'playing':
                    act = discord.Activity(type=discord.ActivityType.playing, name=text)
                elif rtype == 'watching':
                    act = discord.Activity(type=discord.ActivityType.watching, name=text)
                elif rtype == 'listening':
                    act = discord.Activity(type=discord.ActivityType.listening, name=text)
                else:
                    await message.channel.send("```Invalid type. Use playing, watching, or listening.```")
                    return
                
                await self.change_presence(activity=act)
                await message.channel.send(f"```RPC set to {rtype} {text}```")

        except Exception as e:
            await message.channel.send(f"```Error: {str(e)}```")

def run_all_clients():
    clients = [SafeSelfBot(token_index=i) for i in range(len(TOKENS))]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def start_all():
        tasks = [c.start(t) for c, t in zip(clients, TOKENS)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"[Client {i + 1}] Crashed: {r}")

    try:
        loop.run_until_complete(start_all())
    except KeyboardInterrupt:
        print("Shutting down all clients...")
    finally:
        for c in clients:
            if not c.is_closed():
                loop.run_until_complete(c.close())
        loop.close()

if __name__ == "__main__":
    run_all_clients()