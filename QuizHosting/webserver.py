import traceback
from flask import Flask, request, abort, render_template
import asyncio
import discord
from datetime import datetime
import os
import threading

app = Flask('')
bot = None  # Global variable to store the bot instance

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/terms-of-service')
def terms_of_service():
    return render_template("terms-of-service.html")

@app.route('/privacy-policy')
def privacy_policy():
    return render_template("privacy-policy.html")


WEBHOOK_PASSWORD = os.environ['key2']

def start_webhook_server(bot_instance):
    global bot
    bot = bot_instance
    app.run(host="0.0.0.0", port=5000)

@app.route('/dblwebhook', methods=['POST'])
async def dbl_webhook():
    try:
        if request.headers.get('Authorization') != WEBHOOK_PASSWORD:
            app.logger.error("Unauthorized webhook attempt")
            abort(401)

        data = request.json
        user_id = str(data['user'])
        app.logger.info(f"Received upvote from user {user_id}")

        # Check if the user exists in the database
        user_profile = await bot.get_user_profile(user_id)
        
        if user_profile is None:
            app.logger.warning(f"User {user_id} not found in database. Creating new profile.")
            user_profile = UserProfile(user_id)
            await bot.save_user_profile(user_profile)

        # Update the last upvote time and add random powerups
        now = datetime.utcnow()
        user_profile.last_upvote_date = now
        
        # Add random powerups
        powerup_result = await bot.add_random_powerups(user_id)

        # Update the database
        await bot.save_user_profile(user_profile)

        # Create and send the confirmation embed
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
            await user.send(embed=embed)
            app.logger.info(f"Sent upvote confirmation to user {user_id}")
        else:
            app.logger.warning(f"Unable to find Discord user {user_id}")

        return '', 200
    except Exception as e:
        app.logger.error(f"Error processing webhook: {str(e)}")
        app.logger.error(traceback.format_exc())
        return 'Internal Server Error', 500

@app.route('/test', methods=['GET'])
def test():
    return 'Webhook server is running', 200

def run():
    app.run(host="0.0.0.0", port=5000, debug=True)
    print(app.url_map)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()