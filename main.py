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
        self.rpc_list = []
        self.rpc_task = None
        self.rpc_index = 0

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {"prefix": "-", "safe_mode": True}

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    async def setup_hook(self):
        print(f"[Client {self.token_index + 1}] Setting up...")
        pass

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

    def build_activity(self, rpc_entry):
        rtype = rpc_entry['type']
        text = rpc_entry['text']
        image = rpc_entry.get('image')
        small = rpc_entry.get('small_image')
        assets = {}
        if image:
            assets['large_image'] = image
            assets['large_text'] = text
        if small:
            assets['small_image'] = small

        if rtype == 'playing':
            return discord.Activity(type=discord.ActivityType.playing, name=text, assets=assets)
        elif rtype == 'listening':
            return discord.Activity(type=discord.ActivityType.listening, name=text, assets=assets)
        elif rtype == 'watching':
            return discord.Activity(type=discord.ActivityType.watching, name=text, assets=assets)
        elif rtype == 'streaming':
            return discord.Streaming(name=text, url="https://twitch.tv/yourusername")
        return None

    async def _rpc_rotation_loop(self):
        try:
            while self.rpc_list:
                if len(self.rpc_list) == 1:
                    self.rpc_index = 0
                    act = self.build_activity(self.rpc_list[0])
                    if act: await self.change_presence(activity=act)
                    await asyncio.sleep(30)
                    continue
                self.rpc_index %= len(self.rpc_list)
                act = self.build_activity(self.rpc_list[self.rpc_index])
                if act: await self.change_presence(activity=act)
                self.rpc_index = (self.rpc_index + 1) % len(self.rpc_list)
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Client {self.token_index + 1}] RPC loop error: {e}")

    def restart_rpc_rotation(self):
        if self.rpc_task and not self.rpc_task.done():
            self.rpc_task.cancel()
        self.rpc_index = 0
        if self.rpc_list:
            self.rpc_task = asyncio.create_task(self._rpc_rotation_loop())

    async def on_message(self, message):
        # Skip if the message is from ourselves
        if message.author == self.user:
            return

        # DEBUG PRINT
        print(f"RAW MESSAGE: {message.content}")

        channel_key = str(message.channel.id)
        user_key = str(message.author.id)
        if channel_key not in self.last_messages:
            self.last_messages[channel_key] = {}
        self.last_messages[channel_key][user_key] = message.content

        # Get the prefix
        prefix = self.config.get('prefix', '-')

        # Check if the message starts with the prefix
        if not message.content.startswith(prefix):
            return

        # DEBUG PRINT
        print(f"PREFIX MATCH! Command: {message.content}")

        args = message.content[len(prefix):].strip().split()
        cmd = args[0].lower() if args else ""
        rest_args = args[1:]

        print(f"EXECUTING: {cmd}")

        async def get_user_from_arg(arg):
            if arg.startswith('<@') and arg.endswith('>'):
                uid = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                return await self.fetch_user(uid)
            elif arg.isdigit():
                return await self.fetch_user(int(arg))
            return None

        try:
            if cmd == 'help':
                embed = discord.Embed(title="Selfbot Commands", color=0x7289da)
                embed.add_field(name="Utility", value=f"```{prefix}help\n{prefix}setprefix <char>\n{prefix}say <text>\n{prefix}ping```", inline=False)
                await message.channel.send(embed=embed)

            elif cmd == 'setprefix':
                if rest_args:
                    self.config['prefix'] = rest_args[0]
                    self.save_config()
                    await message.channel.send(f"```Prefix changed to {self.config['prefix']}```")
                else:
                    await message.channel.send(f"```Current prefix: {self.config['prefix']}```")

            elif cmd == 'ping':
                await message.channel.send(f"```Ping: {round(self.latency * 1000, 2)}ms```")

            elif cmd == 'say':
                text = " ".join(rest_args)
                if text: await message.channel.send(text)

            elif cmd == 'mock':
                target_user = await get_user_from_arg(rest_args[0]) if rest_args else None
                if target_user:
                    last_msg = self.last_messages.get(str(message.channel.id), {}).get(str(target_user.id), "No recent messages.")
                    await message.channel.send(f"```\n{self.bypass_text(last_msg)}\n```")

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