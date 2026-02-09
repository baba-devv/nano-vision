import asyncio
import threading
import telegram
from telegram.request import HTTPXRequest


class AsyncTelegramNotifier:
    def __init__(self, config: dict):
        """Initialize the Telegram Notifier with bot token and chat ID."""
        self.bot_token = config.get("telegram_notifications", {}).get("bot_token", None)
        self.chat_id = config.get("telegram_notifications", {}).get("chat_id", None)

        if not self.bot_token or not self.chat_id:
            raise ValueError("Telegram bot token and chat ID must be provided in the config under 'telegram_notifications'.")

        self.bot = telegram.Bot(token=self.bot_token)

        # STRATEGY: Build a custom request object with generous timeouts
        self.request_config = HTTPXRequest(
            connect_timeout=30.0, # Time to find the server
            read_timeout=30.0,    # Time to wait for response
            write_timeout=60.0,   # Time to upload the image
            pool_timeout=10.0     # Time to wait for a free connection
        )

        self.loop = asyncio.new_event_loop() # get the asyncio event loop
        
        # run the async loop in its own permanent background thread
        self.t = threading.Thread(target=self._start_loop, daemon=True)
        self.t.start()


    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


    async def _send_message_async(self, message, image_stream=None):
        """Asynchronous method to send message via Telegram bot."""

        print(f"Couroutine: Sending Telegram message: {message}, image: {image_stream is not None}")

        async with self.bot:
            try:
                if image_stream:
                    print(f"Uploading image...")
                    await self.bot.send_photo(
                        chat_id=self.chat_id, 
                        photo=image_stream, 
                        caption=message,
                        write_timeout=60,  # Allow up to 60s for the upload
                        connect_timeout=20 # Allow up to 20s to establish connection
                    )
                else:
                    await self.bot.send_message(
                        chat_id=self.chat_id, 
                        text=message
                    )
                print("✓ Telegram message successfully delivered.")
            except Exception as e:
                print(f"✗ Telegram Error: {e}")


    def send_message(self, message, image_stream=None):
        """Thread-safe wrapper to send message from sync code - sends the task to the async loop."""

        print(f"Sending Telegram message: {message}, image: {image_stream is not None}")
        asyncio.run_coroutine_threadsafe(
            self._send_message_async(message, image_stream), self.loop
        )
        print("Message sent request queued.")