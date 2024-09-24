import os
import threading
import logging
import traceback
from datetime import datetime

import asyncio
from flask import Flask, request, abort, render_template, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

import discord
from discord.ext import commands

from shared import app, bot
from main import QuizBot


app = Flask(__name__)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configure logging
logging.basicConfig(filename='console.log', level=logging.INFO)
logger = logging.getLogger(__name__)

# Discord bot setup
bot = QuizBot()

WEBHOOK_PASSWORD = os.environ.get('key2')

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/terms-of-service')
def terms_of_service():
    return render_template("terms-of-service.html")

@app.route('/privacy-policy')
def privacy_policy():
    return render_template("privacy-policy.html")

@app.route('/dblwebhook', methods=['POST'])
def dbl_webhook():
    try:
        if request.headers.get('Authorization') != WEBHOOK_PASSWORD:
            logger.error("Unauthorized webhook attempt")
            abort(401)
        
        data = request.json
        user_id = str(data['user'])
        logger.info(f"Received upvote from user {user_id}")
        
        # Use asyncio to run the asynchronous function in the background
        asyncio.create_task(process_upvote(user_id))
        
        return '', 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return 'Internal Server Error', 500


async def process_upvote(user_id: str):
    try:
        # Get or create user profile
        user_profile = await bot.get_user_profile(user_id)
        if user_profile is None:
            logger.warning(f"User {user_id} not found in database. Creating new profile.")
            user_profile = await bot.create_user_profile(user_id)
        
        # Update upvote information
        user_profile.update_upvote()
        
        # Add random powerups
        powerup_result = await bot.add_random_powerups(user_id)
        
        # Update the database
        await bot.save_user_profile(user_profile)
        
        # Send confirmation message to user
        await send_upvote_confirmation(user_id, powerup_result)
    except Exception as e:
        logger.error(f"Error processing upvote for user {user_id}: {str(e)}")

async def send_upvote_confirmation(user_id: str, powerup_result: dict):
    embed = discord.Embed(
        title="Thanks for Upvoting!",
        description=f"You've received {powerup_result['total_powerups']} powerups!",
        color=discord.Color.green()
    )
    embed.add_field(name="Upvote Streak", value=f"{powerup_result['upvote_count']} day{'s' if powerup_result['upvote_count'] > 1 else ''}")

    powerups_text = "\n".join([f"{name.replace('_', ' ').title()}: {count}" for name, count in powerup_result['powerups_added'].items() if count > 0])
    embed.add_field(name="Powerups Received", value=powerups_text, inline=False)

    embed.set_footer(text="Keep voting daily for bonus powerups!")

    user = bot.get_user(int(user_id))
    if user:
        try:
            await user.send(embed=embed)
            app.logger.info(f"Sent upvote confirmation to user {user_id}")
        except discord.errors.Forbidden:
            app.logger.warning(f"Unable to send DM to user {user_id}")
    else:
        app.logger.warning(f"Unable to find Discord user {user_id}")

@app.route('/test', methods=['GET'])
def test():
    return 'Webhook server is running', 200

@app.route('/console', methods=['GET'])
def console():
    if os.path.exists('console.log'):
        return send_file('console.log', as_attachment=True)
    else:
        return 'Log file not found', 404

def run_webhook_server():
    app.run(host="0.0.0.0", port=5000)
