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
        self.auto_reacts = {}
        self.auto_mocks = {} 

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

        # --- LISTEN FOR TARGETS ---
        if message.author.id != self.user.id:
            # 1. Auto-react
            if str(message.author.id) in self.auto_reacts:
                for emoji in self.auto_reacts[str(message.author.id)]:
                    try:
                        await message.add_reaction(emoji)
                    except Exception:
                        pass
            
            # 2. Auto-mock (Repeats their message instantly as normal text)
            if str(message.author.id) in self.auto_mocks:
                safe_text = self.bypass_text(message.content)
                if safe_text.strip(): 
                    await message.channel.send(safe_text) # NO CODE BLOCKS
            
            return 

        # --- COMMAND HANDLING ---
        prefix = self.config.get('prefix', '-')
        if not message.content.startswith(prefix):
            return

        args = message.content[len(prefix):].strip().split()
        cmd = args[0].lower() if args else ""
        rest_args = args[1:]

        try:
            # --- HELP MENU ---
            if cmd == 'help':
                help_text = (
                    "```ini\n"
                    "374 SelfBot | Advanced Platform\n"
                    f"Prefix: {prefix}\n\n"
                    "[ UTILITY ]\n"
                    f"{prefix}ping, {prefix}setprefix, {prefix}avatar, {prefix}banner\n\n"
                    "[ MODERATION ]\n"
                    f"{prefix}purge, {prefix}dm\n\n"
                    "[ FUN ]\n"
                    f"{prefix}react, {prefix}mock, {prefix}stop\n\n"
                    "[ INFO ]\n"
                    f"{prefix}userinfo, {prefix}serverinfo\n\n"
                    "[ RPC ]\n"
                    f"{prefix}rpc <playing/watching/listening> <text>\n"
                    "```"
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

            # --- AVATAR ---
            elif cmd == 'avatar':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    arg = rest_args[0]
                    if arg.startswith('<@') and arg.endswith('>'):
                        target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                        target = message.guild.get_member(target_id) if message.guild else None
                        if not target:
                            await message.channel.send("```User not in cache. Reply to their message instead.```")
                            return
                else:
                    target = message.author

                if not target:
                    await message.channel.send("```User not found.```")
                    return

                avatar_url = target.display_avatar.url if hasattr(target, 'display_avatar') else target.avatar.url
                if avatar_url:
                    await message.channel.send(f"**{target.name}'s Avatar**\n{avatar_url}")
                else:
                    await message.channel.send("```User has no avatar.```")

            # --- BANNER ---
            elif cmd == 'banner':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    arg = rest_args[0]
                    if arg.startswith('<@') and arg.endswith('>'):
                        target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                        target = message.guild.get_member(target_id) if message.guild else None
                else:
                    target = message.author

                if target and hasattr(target, 'banner') and target.banner:
                    await message.channel.send(f"**{target.name}'s Banner**\n{target.banner.url}")
                else:
                    await message.channel.send("```User has no banner or is not cached.```")

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
                await message.channel.send(f"```Purged {deleted} messages.```")

            elif cmd == 'dm':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -dm <@user> <message>```")
                    return
                
                arg = rest_args[0]
                if arg.startswith('<@') and arg.endswith('>'):
                    target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                    target = message.guild.get_member(target_id) if message.guild else None
                    if not target:
                        await message.channel.send("```User not in cache.```")
                        return
                    
                    text = " ".join(rest_args[1:])
                    try:
                        await target.send(text)
                        await message.channel.send(f"```Sent DM to {target.name}```")
                    except Exception:
                        await message.channel.send("```Failed to send DM (User has DMs closed).```")

            # --- FUN & INTERACTIONS ---
            elif cmd == 'mock':
                if not rest_args:
                    await message.channel.send("```Usage: -mock <@user>```")
                    return
                
                arg = rest_args[0]
                if arg.startswith('<@') and arg.endswith('>'):
                    target_id = arg.replace('<@', '').replace('>', '').replace('!', '')
                else:
                    target_id = arg
                
                if str(target_id) == str(self.user.id):
                    await message.channel.send("```You cannot mock yourself.```")
                    return
                
                self.auto_mocks[str(target_id)] = True
                await message.channel.send(f"```Now mocking user ID {target_id}. Every message they send will be repeated.```")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -react <@user> <emoji>```")
                    return
                
                arg = rest_args[0]
                emoji = rest_args[1]
                
                if arg.startswith('<@') and arg.endswith('>'):
                    target_id = arg.replace('<@', '').replace('>', '').replace('!', '')
                else:
                    target_id = arg
                
                if str(target_id) == str(self.user.id):
                    await message.channel.send("```You cannot autoreact to yourself.```")
                    return
                
                self.auto_reacts[str(target_id)] = [emoji]
                await message.channel.send(f"```Autoreact set for user ID {target_id} with {emoji}```")

            elif cmd == 'stop':
                self.auto_reacts.clear()
                self.auto_mocks.clear()
                await message.channel.send("```All auto-reacts and auto-mocks have been cleared.```")

            # --- INFORMATION ---
            elif cmd == 'userinfo':
                target = message.author
                if rest_args:
                    arg = rest_args[0]
                    if arg.startswith('<@') and arg.endswith('>'):
                        target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                        target = message.guild.get_member(target_id) if message.guild else None
                
                if target:
                    info_text = (
                        f"```ini\n"
                        f"User: {target.name}\n"
                        f"ID: {target.id}\n"
                        f"Created: {target.created_at.strftime('%Y-%m-%d')}\n"
                        f"```"
                    )
                    await message.channel.send(info_text)
                else:
                    await message.channel.send("```User not in cache.```")

            elif cmd == 'serverinfo':
                if not message.guild:
                    await message.channel.send("```Must be used in a server.```")
                    return
                server_text = (
                    f"```ini\n"
                    f"Server: {message.guild.name}\n"
                    f"Members: {message.guild.member_count}\n"
                    f"Created: {message.guild.created_at.strftime('%Y-%m-%d')}\n"
                    f"```"
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