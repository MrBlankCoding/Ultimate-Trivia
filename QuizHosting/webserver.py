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


app = Flask(__name__)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configure logging
logging.basicConfig(filename='console.log', level=logging.INFO)
logger = logging.getLogger(__name__)

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
    from main import send_upvote_confirmation, process_upvote
    try:
        if request.headers.get('Authorization') != WEBHOOK_PASSWORD:
            logger.error("Unauthorized webhook attempt")
            abort(401)
        
        data = request.json
        user_id = str(data['user'])
        logger.info(f"Received upvote from user {user_id}")
        
        # Check if there is an existing event loop and run accordingly
        try:
            loop = asyncio.get_running_loop()
            # If we are already in an event loop, we create a task
            loop.create_task(process_upvote(user_id))
        except RuntimeError:  # No event loop exists, so we create one
            asyncio.run(process_upvote(user_id))
        
        return '', 200
    except Exception as e:
        logger.error(f"Error processing webhook: {traceback.format_exc()}")
        return 'Internal Server Error', 500


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
