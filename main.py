import discord
import aiohttp
import json
import os
import re
import asyncio
import io

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
        self.cached_users = {} # NEW: Global user cache
        self.active_channels = set() # NEW: Tracks channels to refresh
        self.cache_task = None

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
        
        # Start the background cache refresher
        if self.cache_task is None or self.cache_task.done():
            self.cache_task = asyncio.create_task(self.background_cache_refresher())

    # --- BACKGROUND CACHE REFRESHER ---
    async def background_cache_refresher(self):
        while True:
            try:
                for channel in list(self.active_channels):
                    try:
                        # Fetch last 20 messages to keep cache updated without rate limits
                        async for msg in channel.history(limit=20):
                            if not msg.author.bot:
                                self.cached_users[msg.author.id] = msg.author
                    except Exception:
                        pass # Ignore if we lost access to the channel
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(3) # Refresh every 3 seconds

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

    async def get_cached_user(self, message, arg):
        # Helper to grab users without triggering 403 errors
        target_id = None
        if arg.startswith('<@') and arg.endswith('>'):
            target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
        elif arg.isdigit():
            target_id = int(arg)
        
        if not target_id:
            return None
            
        # 1. Check global cache
        if target_id in self.cached_users:
            return self.cached_users[target_id]
            
        # 2. Check guild cache
        if message.guild:
            member = message.guild.get_member(target_id)
            if member:
                self.cached_users[target_id] = member
                return member

        # 3. Try to fetch via API (might fail, but worth a shot)
        try:
            user = await self.fetch_user(target_id)
            self.cached_users[target_id] = user
            return user
        except Exception:
            return None

    async def on_message(self, message):
        if message.author.bot:
            return
            
        # Add channel to active list for background refresher
        if message.guild:
            self.active_channels.add(message.channel)

        # Cache this author instantly
        self.cached_users[message.author.id] = message.author

        # --- LISTEN FOR TARGETS ---
        if message.author.id != self.user.id:
            if str(message.author.id) in self.auto_reacts:
                for emoji in self.auto_reacts[str(message.author.id)]:
                    try:
                        await message.add_reaction(emoji)
                    except Exception:
                        pass
            
            if str(message.author.id) in self.auto_mocks:
                safe_text = self.bypass_text(message.content)
                if safe_text.strip(): 
                    await message.channel.send(safe_text)
            
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

            # --- AVATAR (NEW FORMAT & CACHE FIX) ---
            elif cmd == 'avatar':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                else:
                    target = message.author

                avatar_url = target.display_avatar.url if hasattr(target, 'display_avatar') else target.avatar.url
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            file = discord.File(io.BytesIO(img_data), filename="avatar.png")
                            # Fixed Output Format exactly as requested
                            await message.channel.send(f"> **{target.name}’s Avatar**", file=file)
                        else:
                            await message.channel.send("```Failed to download avatar.```")

            # --- BANNER (NEW FORMAT & CACHE FIX) ---
            elif cmd == 'banner':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                else:
                    target = message.author

                if hasattr(target, 'banner') and target.banner:
                    banner_url = target.banner.url
                    async with aiohttp.ClientSession() as session:
                        async with session.get(banner_url) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                file = discord.File(io.BytesIO(img_data), filename="banner.png")
                                await message.channel.send(f"> **{target.name}’s Banner**", file=file)
                            else:
                                await message.channel.send("```Failed to download banner.```")
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
                
                target = await self.get_cached_user(message, rest_args[0])
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                text = " ".join(rest_args[1:])
                try:
                    await target.send(text)
                    await message.channel.send(f"```Sent DM to {target.name}```")
                except Exception:
                    await message.channel.send("```Failed to send DM (User has DMs closed).```")

            # --- FUN & INTERACTIONS (MOCK FIX) ---
            elif cmd == 'mock':
                if not rest_args:
                    await message.channel.send("```Usage: -mock <@user>```")
                    return
                
                target = await self.get_cached_user(message, rest_args[0])
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("```You cannot mock yourself.```")
                    return
                
                self.auto_mocks[str(target.id)] = True
                await message.channel.send(f"```Now mocking {target.name}. Every message they send will be repeated.```")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -react <@user> <emoji>```")
                    return
                
                target = await self.get_cached_user(message, rest_args[0])
                emoji = rest_args[1]
                
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("```You cannot autoreact to yourself.```")
                    return
                
                self.auto_reacts[str(target.id)] = [emoji]
                await message.channel.send(f"```Autoreact set for {target.name} with {emoji}```")

            elif cmd == 'stop':
                self.auto_reacts.clear()
                self.auto_mocks.clear()
                await message.channel.send("```All auto-reacts and auto-mocks have been cleared.```")

            # --- INFORMATION ---
            elif cmd == 'userinfo':
                target = message.author
                if rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                
                info_text = (
                    f"```ini\n"
                    f"User: {target.name}\n"
                    f"ID: {target.id}\n"
                    f"Created: {target.created_at.strftime('%Y-%m-%d')}\n"
                    f"```"
                )
                await message.channel.send(info_text)

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