from flask import Flask

app = Flask('')
bot = None  # Global variable to store the bot instance

def set_bot(bot_instance):
    global bot
    bot = bot_instance