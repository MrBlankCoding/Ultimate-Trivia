# Standard library imports
import asyncio
import base64
import os
import random
import time as time_module
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import threading
import html

# Third-party library imports
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
import redis.asyncio as redis
import topgg

# Project-specific imports
from webserver import run_webhook_server
from shared import set_bot
from asyncio import Lock


DISCORD_TOKEN = os.environ['key']
WEBHOOK_PASSWORD = os.environ['key2']
REDIS_PASSWORD = os.environ['key3']
TOPGG = os.environ['key4']

#this guy
USERS_PER_PAGE = 10
API_COOLDOWN = 5  # seconds
last_api_call = datetime.utcnow()
TOP_GG_URL = "https://top.gg/bot/1282093835156979816"
api_lock = Lock()
API_URL = "https://opentdb.com/api.php"
CATEGORY_MAP = {
    "general": 9,
    "books": 10,
    "film": 11,
    "music": 12,
    "theatre": 13,
    "television": 14,
    "video_games": 15,
    "board_games": 16,
    "science": 17,
    "computers": 18,
    "mathematics": 19,
    "mythology": 20,
    "sports": 21,
    "geography": 22,
    "history": 23,
    "politics": 24,
    "art": 25,
    "celebrities": 26,
    "animals": 27,
    "vehicles": 28,
    "comics": 29,
    "gadgets": 30,
    "anime_manga": 31,
    "cartoons": 32,
}

class UpvoteView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.Button(label="Upvote on Top.gg", url=TOP_GG_URL, style=discord.ButtonStyle.link))
        
class UserProfile:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.total_points = 0
        self.questions_answered = 0
        self.correct_answers = 0
        self.current_streak = 0
        self.longest_streak = 0
        self.last_daily_quiz = None
        self.last_milestone = 0
        self.upvote_count = 0
        self.last_upvote_date = None
        self.powerups = {
            "streak_sponsor": 2,
            "double_life": 2,
            "freeze_frame": 2,
            "double_points": 2
        }
        self.tier = "Wood"  # Default tier
        self.weekly_points = 0
        self.last_weekly_reset = datetime.now()
        self.notifications_enabled = False  # Default to True
        self.quizzes_completed = 0  # New attribute to track completed quizzes

    @property
    def accuracy(self) -> float:
        if self.questions_answered == 0:
            return 0.0
        return (self.correct_answers / self.questions_answered) * 100

    async def update_stats(self, points: int, correct: bool):
        self.total_points += points
        self.weekly_points += points
        self.questions_answered += 1
        if correct:
            self.correct_answers += 1

    def update_streak(self):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if self.last_daily_quiz is None:
            self.current_streak = 1
        else:
            days_since_last_quiz = (today - self.last_daily_quiz).days
            
            if days_since_last_quiz == 1:
                self.current_streak += 1
            elif days_since_last_quiz > 1:
                self.current_streak = 1
            
            self.longest_streak = max(self.current_streak, self.longest_streak)
        
        self.last_daily_quiz = today

    def reset_weekly_points(self):
        self.weekly_points = 0
        self.last_weekly_reset = datetime.now()

    def add_powerups(self, powerups: Dict[str, int]):
        for powerup, count in powerups.items():
            self.powerups[powerup] += count

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "total_points": self.total_points,
            "questions_answered": self.questions_answered,
            "correct_answers": self.correct_answers,
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
            "last_daily_quiz": self.last_daily_quiz.isoformat() if self.last_daily_quiz else None,
            "powerups": self.powerups,
            "tier": self.tier,
            "weekly_points": self.weekly_points,
            "last_weekly_reset": self.last_weekly_reset.isoformat() if self.last_weekly_reset else None,
            "notifications_enabled": self.notifications_enabled,
            "upvote_count": self.upvote_count,
            "last_upvote_date": self.last_upvote_date.isoformat() if self.last_upvote_date else None,
            "quizzes_completed": self.quizzes_completed  # Add this line
        }

    @classmethod
    async def from_dict(cls, data: dict) -> 'UserProfile':
        profile = cls(data["user_id"])
        profile.total_points = data.get("total_points", 0)
        profile.questions_answered = data.get("questions_answered", 0)
        profile.correct_answers = data.get("correct_answers", 0)
        profile.current_streak = data.get("current_streak", 0)
        profile.longest_streak = data.get("longest_streak", 0)
        profile.last_daily_quiz = datetime.fromisoformat(data["last_daily_quiz"]) if data.get("last_daily_quiz") else None
        if isinstance(profile.last_daily_quiz, str):
            try:
                profile.last_daily_quiz = datetime.fromisoformat(profile.last_daily_quiz)
            except ValueError:
                profile.last_daily_quiz = None
        profile.powerups = data.get("powerups", {
            "streak_sponsor": 2,
            "double_life": 2,
            "freeze_frame": 2,
            "double_points": 2
        })
        profile.tier = data.get("tier", "Stone")
        profile.weekly_points = data.get("weekly_points", 0)
        profile.last_weekly_reset = data.get("last_weekly_reset")
        if isinstance(profile.last_weekly_reset, str):
            try:
                profile.last_weekly_reset = datetime.fromisoformat(profile.last_weekly_reset)
            except ValueError:
                profile.last_weekly_reset = datetime.now()
        profile.notifications_enabled = data.get("notifications_enabled", True)
        profile.quizzes_completed = data.get("quizzes_completed", 0)  # Add this line
        profile.upvote_count = data.get("upvote_count", 0)
        profile.last_upvote_date = datetime.fromisoformat(data["last_upvote_date"]) if data.get("last_upvote_date") else None
        return profile

class PowerupConfig:
    def __init__(self):
        self.promotion_rewards = {
            "streak_sponsor": 2,
            "double_life": 2,
            "freeze_frame": 2,
            "double_points": 2
        }
        self.demotion_rewards = {
            "streak_sponsor": 1,
            "double_life": 1,
            "freeze_frame": 1,
            "double_points": 1
        }
        self.top_rewards = {
            1: {"streak_sponsor": 3, "double_life": 3, "freeze_frame": 3, "double_points": 3},
            2: {"streak_sponsor": 2, "double_life": 2, "freeze_frame": 2, "double_points": 2},
            3: {"streak_sponsor": 1, "double_life": 1, "freeze_frame": 1, "double_points": 1}
        }

class QuizBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, command_prefix='!')
        self.daily_category = None
        self.daily_category_date = None
        self.tiers = ["Wood", "Stone", "Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Titanium"]
        
        # MongoDB connection
        mongo_uri = 'mongodb+srv://mrblankcoding:CiTqGQM4Y3U5PNAI@ultimate-trivia.7olcj.mongodb.net/?retryWrites=true&w=majority&appName=Ultimate-trivia'
        self.redis = redis.Redis(host='redis-16642.c16.us-east-1-2.ec2.redns.redis-cloud.com', port=16642, password=REDIS_PASSWORD)
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client['ultimate_trivia']
        self.topgg_client = None
        self.leaderboard_cache = {}
        self.rank_cache = {}
        
        self.weekly_leaderboard = WeeklyLeaderboard(self.db)
        self.leaderboard_lock = asyncio.Lock()
        self.user_profiles_collection = self.db['user_profiles']
        self.user_profiles = {}
        self.views = []
        self.powerup_config = PowerupConfig()

    async def setup_hook(self):
        # Initialize Top.gg client
        await self.init_topgg_client()

        # Load data and start background tasks
        await self.load_data()
        await self.tree.sync()
        await self.start_background_tasks()

    async def init_topgg_client(self):
        self.topgg_client = topgg.DBLClient(self, TOPGG, autopost=True)

    async def start_background_tasks(self):
        self.check_weekly_reset.start()
        self.daily_category_reset.start()
        self.daily_notifications.start()
        self.update_leaderboard_cache.start()
        self.check_upvotes.start()
        self.upvote_reminder.start()
        
    async def add_random_powerups(self, user_id: str) -> dict:
        user_profile = await self.get_user_profile(user_id)
        powerup_types = list(user_profile.powerups.keys())
        
        bonus_powerups = min(user_profile.upvote_count // 5, 5)
        
        powerups_added = {powerup: 0 for powerup in powerup_types}
        for _ in range(5 + bonus_powerups):
            powerup = random.choice(powerup_types)
            user_profile.powerups[powerup] += 1
            powerups_added[powerup] += 1

        return {
            'upvote_count': user_profile.upvote_count,
            'powerups_added': powerups_added,
            'total_powerups': 5 + bonus_powerups
        }
        
    @tasks.loop(minutes=5)
    async def check_upvotes(self):
        current_time = datetime.utcnow()
        twelve_hours_ago = current_time - timedelta(hours=12)

        async for upvote_record in self.db.upvotes.find({'last_upvote': {'$lt': twelve_hours_ago}}):
            user_id = upvote_record['user_id']
            has_voted = await self.topgg_client.get_user_vote(user_id)
            
            if has_voted:
                await self.add_random_powerups(user_id)
                
    @tasks.loop(hours=1)
    async def upvote_reminder(self):
        current_time = datetime.utcnow()
        twelve_hours_ago = current_time - timedelta(hours=12)

        async for user_profile in self.db.user_profiles.find({'notifications_enabled': True}):
            user_id = user_profile['user_id']
            last_upvote = await self.db.upvotes.find_one({'user_id': user_id})
            
            if not last_upvote or last_upvote['last_upvote'] < twelve_hours_ago:
                try:
                    user = await self.fetch_user(int(user_id))
                    embed = discord.Embed(
                        title="Time to Upvote!",
                        description="You can now upvote Ultimate Trivia Bot on Top.gg! Upvoting helps us grow and earns you powerups.",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="Rewards", value="• 5 random powerups\n• Bonus powerups for consistent voting")
                    embed.set_footer(text="Use the /upvote command to get the voting link")
                    
                    await user.send(embed=embed)
                except discord.errors.Forbidden:
                    print(f"Unable to send DM to user {user_id}")
        
    @asynccontextmanager
    async def leaderboard_context(self):
        async with self.leaderboard_lock:
            yield

    @tasks.loop(hours=10)
    async def check_weekly_reset(self):
        now = datetime.utcnow()
        last_reset = await self.get_last_weekly_reset()
        if now - last_reset >= timedelta(days=7):
            await self.perform_weekly_reset()

    async def get_last_weekly_reset(self):
        async with self.leaderboard_context():
            settings = await self.db['bot_settings'].find_one({'_id': 'weekly_reset'})
            if not settings:
                last_reset = datetime.utcnow() - timedelta(days=7)
                await self.db['bot_settings'].update_one(
                    {'_id': 'weekly_reset'},
                    {'$set': {'last_reset': last_reset}},
                    upsert=True
                )
            else:
                last_reset = settings['last_reset']
            return last_reset

    async def perform_weekly_reset(self):
        async with self.leaderboard_context():
            new_tier_assignments = await self.assign_tiers()
            
            for tier in self.tiers:
                users = new_tier_assignments[tier]
                for rank, user_id in enumerate(users, start=1):
                    user_profile = await self.get_user_profile(user_id)
                    old_tier = user_profile.tier
                    user_profile.tier = tier
                    
                    powerups = {"streak_sponsor": 0, "double_life": 0, "freeze_frame": 0, "double_points": 0}
                    
                    if old_tier != tier:
                        if self.tiers.index(tier) > self.tiers.index(old_tier):  # Promotion
                            powerups = {k: v + self.powerup_config.promotion_rewards[k] for k, v in powerups.items()}
                        else:  # Demotion
                            powerups = {k: v + self.powerup_config.demotion_rewards[k] for k, v in powerups.items()}
                    
                    # Top 3 rewards
                    if rank in self.powerup_config.top_rewards:
                        powerups = {k: v + self.powerup_config.top_rewards[rank][k] for k, v in powerups.items()}
                    
                    user_profile.add_powerups(powerups)
                    await self.save_user_profile(user_profile)
                    await self.notify_user(user_id, old_tier, tier, powerups)
            
            # Reset weekly points for all users
            await self.user_profiles_collection.update_many({}, {"$set": {"weekly_points": 0}})
            await self.weekly_leaderboard.reset_weekly()

            # Update last reset time
            now = datetime.utcnow()
            await self.db['bot_settings'].update_one(
                {'_id': 'weekly_reset'},
                {'$set': {'last_reset': now}},
                upsert=True
            )

    async def calculate_dynamic_thresholds(self):
        async with self.leaderboard_context():
            total_users = await self.user_profiles_collection.count_documents({})
            active_users = await self.user_profiles_collection.count_documents({"weekly_points": {"$gt": 0}})
            
            # Calculate the activity ratio
            activity_ratio = active_users / total_users if total_users > 0 else 0
            
            # Adjust tier sizes based on activity ratio
            tier_sizes = [
                max(5, int(10 * activity_ratio)) for _ in range(len(self.tiers) - 1)
            ]
            tier_sizes.append(max(5, total_users - sum(tier_sizes)))  # Last tier gets remaining users
            
            # Calculate percentiles for each tier
            percentiles = [sum(tier_sizes[:i+1]) / total_users for i in range(len(self.tiers))]
            
            # Get weekly points for users at each percentile
            thresholds = []
            for percentile in percentiles[:-1]:  # Exclude the last percentile (100%)
                threshold = await self.user_profiles_collection.find().sort("weekly_points", -1).skip(int(percentile * total_users)).limit(1).next()
                thresholds.append(threshold["weekly_points"])
            
            return dict(zip(self.tiers, thresholds))

    async def assign_tiers(self):
        thresholds = await self.calculate_dynamic_thresholds()
        all_users = await self.user_profiles_collection.find().sort("weekly_points", -1).to_list(length=None)
        
        tier_assignments = {tier: [] for tier in self.tiers}
        
        for user in all_users:
            for tier, threshold in thresholds.items():
                if user["weekly_points"] >= threshold:
                    tier_assignments[tier].append(user["_id"])
                    break
            else:
                tier_assignments[self.tiers[-1]].append(user["_id"])
        
        return tier_assignments

    @tasks.loop(time=time(hour=0, minute=0))  # Run at midnight
    async def daily_notifications(self):
        async for user_data in self.user_profiles_collection.find({"notifications_enabled": True}):
            user_id = user_data["_id"]
            user = self.get_user(int(user_id))
            if user:
                try:
                    profile = await UserProfile.from_dict(user_data)
                    embed = discord.Embed(
                        title="Daily Quiz Reminder",
                        description="The daily quiz is now available!",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="Current Streak", value=f"{profile.current_streak} days", inline=True)
                    embed.add_field(name="Longest Streak", value=f"{profile.longest_streak} days", inline=True)
                    embed.set_footer(text="Use /daily_quiz to take today's quiz!")
                    await user.send(embed=embed)
                except discord.errors.Forbidden:
                    print(f"Unable to send DM to user {user_id}")

    @daily_notifications.before_loop
    async def before_daily_notifications(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def weekly_reset(self):
        now = datetime.now()
        if now.weekday() == 0:  # Monday
            await self.perform_weekly_reset()

    async def load_data(self):
        async with self.leaderboard_context():
            cursor = self.user_profiles_collection.find()
            async for doc in cursor:
                self.user_profiles[str(doc['_id'])] = await UserProfile.from_dict(doc)

    async def save_data(self):
        async with self.leaderboard_context():
            profiles_ops = [
                UpdateOne({'_id': user_id}, {'$set': profile.to_dict()}, upsert=True)
                for user_id, profile in self.user_profiles.items()
            ]
            if profiles_ops:
                await self.user_profiles_collection.bulk_write(profiles_ops)

    @tasks.loop(minutes=5)
    async def update_leaderboard_cache(self):
        for tier in self.tiers:
            await self.cache_tier_leaderboard(tier)
        await self.cache_overall_leaderboard()

    async def cache_tier_leaderboard(self, tier: str):
        pipeline = self.redis.pipeline()
        
        # Get leaderboard data from MongoDB
        cursor = self.db[f"{tier.lower()}_leaderboard"].find().sort("points", -1)
        leaderboard_data = await cursor.to_list(length=None)
        
        # Cache leaderboard data and compute ranks
        for rank, doc in enumerate(leaderboard_data, start=1):
            user_id = doc["user_id"]
            points = doc["points"]
            
            # Cache user data
            pipeline.hset(f"user:{user_id}", mapping={
                "tier": tier,
                "points": points,
                "rank": rank
            })
            
            # Cache leaderboard entry
            pipeline.zadd(f"leaderboard:{tier}", {user_id: points})
        
        # Execute Redis pipeline
        await pipeline.execute()
        
        # Update in-memory cache
        self.leaderboard_cache[tier] = leaderboard_data
        self.rank_cache[tier] = {doc["user_id"]: rank for rank, doc in enumerate(leaderboard_data, start=1)}

    async def cache_overall_leaderboard(self):
        pipeline = self.redis.pipeline()
        
        # Get overall leaderboard data from MongoDB
        cursor = self.user_profiles_collection.find().sort("total_points", -1)
        overall_data = await cursor.to_list(length=None)
        
        # Cache overall leaderboard data and compute ranks
        for rank, doc in enumerate(overall_data, start=1):
            user_id = str(doc["_id"])
            total_points = doc["total_points"]
            
            # Cache user data
            pipeline.hset(f"user:{user_id}:overall", mapping={
                "total_points": total_points,
                "rank": rank
            })
            
            # Cache overall leaderboard entry
            pipeline.zadd("leaderboard:overall", {user_id: total_points})
        
        # Execute Redis pipeline
        await pipeline.execute()
        
        # Update in-memory cache
        self.leaderboard_cache["overall"] = overall_data
        self.rank_cache["overall"] = {str(doc["_id"]): rank for rank, doc in enumerate(overall_data, start=1)}

    async def get_tier_leaderboard(self, tier: str) -> List[Tuple[str, int]]:
        if tier in self.leaderboard_cache:
            return [(doc["user_id"], doc["points"]) for doc in self.leaderboard_cache[tier]]
        else:
            # Fallback to database if cache is not available
            return await super().get_tier_leaderboard(tier)

    async def get_overall_leaderboard(self) -> List[Tuple[str, int]]:
        if "overall" in self.leaderboard_cache:
            return [(str(doc["_id"]), doc["total_points"]) for doc in self.leaderboard_cache["overall"]]
        else:
            # Fallback to database if cache is not available
            return await super().get_overall_leaderboard()

    async def get_user_rank(self, user_id: str, tier: str) -> int:
        if tier in self.rank_cache and user_id in self.rank_cache[tier]:
            return self.rank_cache[tier][user_id]
        else:
            # Fallback to Redis if in-memory cache is not available
            rank = await self.redis.zrevrank(f"leaderboard:{tier}", user_id)
            return rank + 1 if rank is not None else None


    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        # Check cache first
        if user_id in self.user_profiles:
            return self.user_profiles[user_id]

        # If not in cache, fetch from database
        user_data = await self.user_profiles_collection.find_one({"user_id": user_id})
        if user_data:
            user_profile = await UserProfile.from_dict(user_data)
            self.user_profiles[user_id] = user_profile
            return user_profile
        return None
    
    async def create_user_profile(self, user_id: str) -> UserProfile:
        user_profile = UserProfile(user_id)
        await self.save_user_profile(user_profile)
        return user_profile

    async def save_user_profile(self, user_profile: UserProfile):
        await self.user_profiles_collection.update_one(
            {"user_id": user_profile.user_id},
            {"$set": user_profile.to_dict()},
            upsert=True
        )
        self.user_profiles[user_profile.user_id] = user_profile
        
    @tasks.loop(time=time(hour=0, minute=0))  # Run at midnight
    async def daily_category_reset(self):
        await self.set_daily_category()

    async def set_daily_category(self):
        async with self.leaderboard_context():
            self.daily_category = random.choice(list(CATEGORY_MAP.keys()))
            self.daily_category_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            await self.db['bot_settings'].update_one(
                {'_id': 'daily_category'},
                {'$set': {'category': self.daily_category, 'date': self.daily_category_date}},
                upsert=True
            )

    async def get_daily_category(self):
        async with self.leaderboard_context():
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if self.daily_category is None or self.daily_category_date != today:
                daily_category_doc = await self.db['bot_settings'].find_one({'_id': 'daily_category'})
                if daily_category_doc and daily_category_doc['date'] == today:
                    self.daily_category = daily_category_doc['category']
                    self.daily_category_date = daily_category_doc['date']
                else:
                    await self.set_daily_category()
            return self.daily_category

    async def notify_user(self, user_id: str, old_tier: str, new_tier: str, powerups: Dict[str, int]):
        try:
            user = await self.fetch_user(int(user_id))
            if old_tier != new_tier:
                message = f"Your tier has changed from {old_tier} to {new_tier}!\n"
                if self.tiers.index(new_tier) > self.tiers.index(old_tier):
                    message += "Congratulations on your promotion! "
                else:
                    message += "You've been demoted, but don't worry! "
                message += f"You've received the following powerups: {', '.join(f'{count} {name}' for name, count in powerups.items())}"
                await user.send(message)
        except discord.errors.Forbidden:
            print(f"Unable to send DM to user {user_id}")

class WeeklyLeaderboard:
    def __init__(self, db):
        self.db = db
        self.tiers = ["Wood", "Stone", "Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Titanium"]

    async def add_user(self, user_id: str, points: int, tier: str):
        if tier not in self.tiers:
            raise ValueError(f"Invalid tier: {tier}")
        
        await self.db[f"{tier.lower()}_leaderboard"].update_one(
            {"user_id": user_id},
            {"$set": {"points": points, "last_updated": datetime.now()}},
            upsert=True
        )

    async def get_leaderboard(self, tier: str) -> List[Tuple[str, int]]:
        if tier not in self.tiers:
            raise ValueError(f"Invalid tier: {tier}")
        
        cursor = self.db[f"{tier.lower()}_leaderboard"].find().sort("points", -1)
        return [(doc["user_id"], doc["points"]) async for doc in cursor]

    async def reset_weekly(self):
        for tier in self.tiers:
            await self.db[f"{tier.lower()}_leaderboard"].delete_many({})
        self.last_reset = datetime.now()
        
bot = QuizBot()
set_bot(bot)

def decode_base64(text: str) -> str:
    """Decode base64 encoded text and then decode HTML entities."""
    decoded = base64.b64decode(text).decode('utf-8')
    return html.unescape(decoded)

async def fetch_questions(category: Optional[str] = None, amount: int = 5, difficulty: Optional[str] = None) -> List[Dict[str, any]]:
    global last_api_call

    async with api_lock:
        # Check if we need to wait before making another API call
        now = datetime.utcnow()
        if now - last_api_call < timedelta(seconds=API_COOLDOWN):
            wait_time = API_COOLDOWN - (now - last_api_call).total_seconds()
            await asyncio.sleep(wait_time)

        params = {
            "amount": amount,
            "type": "multiple",
            "encode": "base64"
        }
        if category and category != "random":
            if category.lower() in CATEGORY_MAP:
                params["category"] = CATEGORY_MAP[category.lower()]
        
        if difficulty and difficulty != "random":
            params["difficulty"] = difficulty.lower()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        
                        # Decode base64 encoded strings and include difficulty
                        for question in results:
                            question["question"] = decode_base64(question["question"])
                            question["correct_answer"] = decode_base64(question["correct_answer"])
                            question["incorrect_answers"] = [decode_base64(answer) for answer in question["incorrect_answers"]]
                            # Ensure difficulty is included (API should provide this, but we'll set a default just in case)
                            if "difficulty" not in question:
                                question["difficulty"] = difficulty or "medium"
                        
                        last_api_call = datetime.utcnow()  # Update the last API call time
                        return results
                    elif response.status == 429:
                        print("Rate limit reached. Waiting before retrying...")
                        await asyncio.sleep(API_COOLDOWN)
                        return await fetch_questions(category, amount, difficulty)  # Retry
                    else:
                        print(f"API request failed with status code: {response.status}")
                        return []
        except aiohttp.ClientError as e:
            print(f"Error fetching questions from API: {e}")
            return []

def format_question(question: Dict[str, any]) -> Dict[str, any]:
    all_answers = [question["correct_answer"]] + question["incorrect_answers"]
    random.shuffle(all_answers)

    options = {
        chr(65 + i): answer for i, answer in enumerate(all_answers)
    }

    correct_answer = [key for key, value in options.items() if value == question["correct_answer"]]

    return {
        "question": question["question"],
        "options": options,
        "correct": correct_answer,
        "difficulty": question.get("difficulty", "medium")
    }

class APIQuizView(discord.ui.View):
    def __init__(self, bot: 'QuizBot', questions: List[Dict[str, Any]], user: Union[discord.User, discord.Member], quiz_type: str = "standard", time_limit: int = 30):
        super().__init__(timeout=None)
        self.bot = bot
        self.questions = questions
        self.current_question = 0
        self.quiz_type = quiz_type
        self.score = 0
        self.user = user
        self.selected_answer: Optional[str] = None
        self.time_limit = time_limit
        self.question_start_time = 0
        self.timer_task: Optional[asyncio.Task] = None
        self.message: Optional[discord.Message] = None
        self.total_time = 0
        self.correct_answers = 0
        self.incorrect_answers = 0
        self.current_streak = 0
        self.active_powerup = None
        self.powerups = {
            "streak_sponsor": self.streak_sponsor,
            "double_life": self.double_life,
            "freeze_frame": self.freeze_frame,
            "double_points": self.double_points
        }
        self.lives = 1
        self.streak_frozen = False
        self.points_multiplier = 1
        self.answer_buttons = []

    def create_answer_buttons(self):
        self.clear_items()  # Clear any existing items
        
        self.answer_buttons = [
            discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=label)
            for label in "ABCD"
        ]
        for button in self.answer_buttons:
            button.callback = self.create_answer_callback(button.custom_id)
            self.add_item(button)

        # Add Submit and Powerup buttons after the answer buttons
        submit_button = discord.ui.Button(label="Submit", style=discord.ButtonStyle.primary, custom_id="submit")
        submit_button.callback = self.submit_answer
        self.add_item(submit_button)

        powerup_button = discord.ui.Button(label="Powerup", style=discord.ButtonStyle.danger, custom_id="powerup")
        powerup_button.callback = self.powerup_button
        self.add_item(powerup_button)

    def create_answer_callback(self, answer: str):
        async def callback(interaction: discord.Interaction):
            await self.select_answer(interaction, answer)
        return callback

    async def submit_answer(self, interaction: discord.Interaction):
        await self.handle_answer(interaction)

    async def powerup_button(self, interaction: discord.Interaction):
        await self.show_powerup_options(interaction)

    async def select_answer(self, interaction: discord.Interaction, answer: str):
        self.selected_answer = answer
        for button in self.answer_buttons:
            button.style = discord.ButtonStyle.primary if button.custom_id == answer else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    async def send_question(self, channel: discord.abc.Messageable):
        question = self.questions[self.current_question]
        embed = discord.Embed(
            title=f"Question {self.current_question + 1}",
            description=question['question'],
            color=discord.Color.blue()
        )

        for key, value in question['options'].items():
            embed.add_field(name=f"{key}: {value}", value="\u200b", inline=False)

        embed.set_footer(text=f"Time remaining: {self.time_limit} seconds")

        self.question_start_time = time_module.time()
        self.message = await channel.send(embed=embed, view=self)

    async def start_timer(self, channel: discord.abc.Messageable):
        if self.timer_task:
            self.timer_task.cancel()
        self.timer_task = asyncio.create_task(self.question_timer(channel))

    async def question_timer(self, channel: discord.abc.Messageable):
        for i in range(self.time_limit, 0, -1):
            await asyncio.sleep(1)
            if self.message and self.message.embeds:
                embed = self.message.embeds[0]
                embed.set_footer(text=f"Time remaining: {i-1} seconds")
                await self.message.edit(embed=embed)

        await self.handle_timeout(channel)

    async def handle_timeout(self, channel: discord.abc.Messageable):
        self.disable_all_buttons()
        await self.message.edit(view=self)

        embed = discord.Embed(title="Time's up!", description="You ran out of time", color=discord.Color.red())
        await channel.send(embed=embed)

        self.current_question += 1
        self.selected_answer = None

        if self.current_question < len(self.questions):
            self.reset_buttons()
            await self.send_question(channel)
            await self.start_timer(channel)
        else:
            await self.end_quiz(channel)

    def disable_all_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def start_quiz(self, channel: discord.abc.Messageable):
        self.bot.views.append(self)
        self.current_question = 0
        self.create_answer_buttons()  # This should only be called once
        await self.send_question(channel)
        await self.start_timer(channel)

    async def handle_answer(self, interaction: discord.Interaction):
        if self.timer_task:
            self.timer_task.cancel()

        await interaction.response.defer()

        if not self.selected_answer:
            await interaction.followup.send("Please select an answer before submitting.", ephemeral=True)
            return

        question = self.questions[self.current_question]
        correct_answers = set(question['correct'])

        is_correct = self.selected_answer in correct_answers
        is_double_life_active = self.active_powerup == "Double Life" and self.lives == 2

        time_taken = time_module.time() - self.question_start_time
        self.total_time += time_taken

        difficulty = question.get('difficulty', 'medium')
        points = self.calculate_points(is_correct, difficulty, time_taken)

        self.score += points
        self.process_answer(is_correct, points)

        await self.update_question_embed(is_correct, correct_answers, points, time_taken)

        if is_correct or (not is_correct and self.lives == 0):
            await self.move_to_next_question(interaction.channel)
        elif is_double_life_active:
            self.lives -= 1
            self.reset_buttons()
            await interaction.followup.send(f"Incorrect, but you have another chance! Lives left: {self.lives}", ephemeral=True)
        else:
            await self.move_to_next_question(interaction.channel)

    def create_answer_embed(self, question, is_correct, correct_answers):
        embed = discord.Embed(
            title=f"Question {self.current_question + 1}",
            description=question['question'],
            color=discord.Color.green() if is_correct else discord.Color.red()
        )

        for key, value in question['options'].items():
            embed.add_field(name=f"{key}: {value}", value="\u200b", inline=False)

        if self.active_powerup:
            embed.set_footer(text=f"Active Power-up: {self.active_powerup}")

        for button in self.answer_buttons:
            if button.custom_id in correct_answers:
                button.style = discord.ButtonStyle.success
            elif button.custom_id == self.selected_answer and not is_correct:
                button.style = discord.ButtonStyle.danger
            button.disabled = True

        self.children[-2].disabled = True  # Disable submit button
        self.children[-1].disabled = True  # Disable powerup button

        return embed

    def reset_buttons(self):
        for button in self.answer_buttons:
            button.style = discord.ButtonStyle.secondary
            button.disabled = False
        self.children[-2].disabled = False  # Enable submit button
        self.children[-1].disabled = False  # Enable powerup button

    def process_answer(self, is_correct: bool, points: int) -> None:
        if is_correct:
            self.correct_answers += 1
            if not self.streak_frozen:
                self.current_streak += 1
        else:
            self.lives -= 1
            if self.lives == 0:
                self.incorrect_answers += 1
                if not self.streak_frozen:
                    self.current_streak = 0
                    
    async def update_question_embed(self, is_correct: bool, correct_answers: Set[str], points: int, time_taken: float):
        embed = self.message.embeds[0]  # Get the existing embed
        embed.color = discord.Color.green() if is_correct else discord.Color.red()

        # Update the answer fields
        for i, field in enumerate(embed.fields):
            key, value = field.name.split(": ", 1)
            if key in correct_answers:
                embed.set_field_at(i, name=f"✅ {key}: {value}", value="\u200b", inline=False)
            elif key == self.selected_answer and not is_correct:
                embed.set_field_at(i, name=f"❌ {key}: {value}", value="\u200b", inline=False)

        # Add result information
        result_text = f"{'Correct' if is_correct else 'Incorrect'}! {'You earned' if is_correct else 'You lost'} {abs(points)} points."
        embed.add_field(name="Result", value=result_text, inline=False)
        embed.add_field(name="Current Score", value=str(self.score), inline=True)
        embed.add_field(name="Streak", value=str(self.current_streak), inline=True)

        # Update footer
        if self.active_powerup:
            embed.set_footer(text=f"Active Power-up: {self.active_powerup} | Time taken: {time_taken:.1f} seconds")
        else:
            embed.set_footer(text=f"Time taken: {time_taken:.1f} seconds")

        # Remove all buttons
        self.clear_items()

        await self.message.edit(embed=embed, view=self)

    async def move_to_next_question(self, channel):
        self.current_question += 1
        self.selected_answer = None

        user_profile = await self.bot.get_user_profile(str(self.user.id))
        await user_profile.update_stats(self.score, self.correct_answers > self.incorrect_answers)

        self.reset_powerups()

        if self.current_question < len(self.questions):
            self.create_answer_buttons()  # Recreate buttons for the next question
            await self.send_question(channel)
            await self.start_timer(channel)
        else:
            await self.end_quiz(channel)

    def reset_powerups(self):
        self.lives = 1
        self.streak_frozen = False
        self.points_multiplier = 1
        self.active_powerup = None

    async def end_quiz(self, channel: discord.abc.Messageable):
        if self.timer_task:
            self.timer_task.cancel()

        avg_time = self.total_time / len(self.questions) if len(self.questions) > 0 else 0
        accuracy = (self.correct_answers / len(self.questions)) * 100 if len(self.questions) > 0 else 0

        embed = discord.Embed(title="Quiz Completed", color=discord.Color.gold())
        embed.add_field(name="Final Score", value=f"{self.score} points", inline=False)
        embed.add_field(name="Accuracy", value=f"{accuracy:.2f}%", inline=True)
        embed.add_field(name="Avg time per question", value=f"{avg_time:.2f} seconds", inline=True)
        embed.add_field(name="Correct Answers", value=str(self.correct_answers), inline=True)
        embed.add_field(name="Incorrect Answers", value=str(self.incorrect_answers), inline=True)
        embed.set_footer(text=f"Quiz completed by {self.user.display_name}")

        user_id = str(self.user.id)
        user_profile = await self.bot.get_user_profile(user_id)

        if self.quiz_type == "daily":
            user_profile.update_streak()
            user_profile.last_daily_quiz = datetime.now().date()

        # Increment the quizzes_completed count
        user_profile.quizzes_completed += 1

        # Get the user's initial rank
        initial_leaderboard = await self.bot.weekly_leaderboard.get_leaderboard(user_profile.tier)
        initial_rank = next((i for i, (uid, _) in enumerate(initial_leaderboard) if uid == user_id), None)

        # Update the user's points and add them to the leaderboard
        user_profile.weekly_points += self.score
        await self.bot.weekly_leaderboard.add_user(user_id, user_profile.weekly_points, user_profile.tier)

        # Get the user's new rank
        updated_leaderboard = await self.bot.weekly_leaderboard.get_leaderboard(user_profile.tier)
        new_rank = next((i for i, (uid, _) in enumerate(updated_leaderboard) if uid == user_id), None)

        # Calculate the change in rank
        if initial_rank is not None and new_rank is not None:
            rank_change = initial_rank - new_rank
            if rank_change > 0:
                embed.add_field(name="Tier Ranking", value=f"You moved up {rank_change} place{'s' if rank_change > 1 else ''} in the {user_profile.tier} tier!", inline=False)
            elif rank_change < 0:
                embed.add_field(name="Tier Ranking", value=f"You moved down {abs(rank_change)} place{'s' if abs(rank_change) > 1 else ''} in the {user_profile.tier} tier.", inline=False)
            else:
                embed.add_field(name="Tier Ranking", value=f"Your rank in the {user_profile.tier} tier remained the same.", inline=False)
        else:
            embed.add_field(name="Tier Ranking", value=f"You are now ranked #{new_rank + 1} in the {user_profile.tier} tier!", inline=False)

        powerups_earned = await self.award_powerups(accuracy, len(self.questions))
        if powerups_earned > 0:
            embed.add_field(name="Powerups Earned", value=f"{powerups_earned}", inline=True)

        await self.bot.save_user_profile(user_profile)

        if self.quiz_type == "daily":
            embed.add_field(name="Current Streak", value=f"{user_profile.current_streak} days", inline=True)
            embed.add_field(name="Longest Streak", value=f"{user_profile.longest_streak} days", inline=True)

        if self in self.bot.views:
            self.bot.views.remove(self)

        await channel.send(embed=embed)

    async def show_powerup_options(self, interaction: discord.Interaction):
        if self.active_powerup:
            await interaction.response.send_message("You've already used a powerup in this quiz.", ephemeral=True)
            return

        user_profile = await self.bot.get_user_profile(str(interaction.user.id))
        
        powerup_view = discord.ui.View()
        for powerup_name, powerup_method in self.powerups.items():
            count = user_profile.powerups.get(powerup_name, 0)
            button = discord.ui.Button(
                label=f"{powerup_name.replace('_', ' ').title()} ({count})",
                custom_id=powerup_name,
                style=discord.ButtonStyle.primary,
                disabled=count == 0
            )
            button.callback = self.create_powerup_callback(powerup_name, powerup_method)
            powerup_view.add_item(button)

        await interaction.response.send_message("Choose a powerup to use:", view=powerup_view, ephemeral=True)

    def create_powerup_callback(self, powerup_name: str, powerup_method: callable):
        async def powerup_callback(interaction: discord.Interaction):
            user_profile = await self.bot.get_user_profile(str(interaction.user.id))
            if user_profile.powerups[powerup_name] <= 0:
                await interaction.response.send_message(f"You don't have any {powerup_name.replace('_', ' ').title()} powerups left.", ephemeral=True)
                return

            result = await powerup_method()
            self.active_powerup = powerup_name.replace('_', ' ').title()
            
            user_profile.powerups[powerup_name] -= 1
            await self.bot.save_data()

            await interaction.response.send_message(f"{result}\nYou have {user_profile.powerups[powerup_name]} {powerup_name.replace('_', ' ').title()} powerups left.", ephemeral=True)
            
            embed = self.message.embeds[0]
            embed.set_footer(text=f"Active Power-up: {self.active_powerup}")
            await self.message.edit(embed=embed)

        return powerup_callback
    
    def calculate_points(self, is_correct: bool, difficulty: str, time_taken: float) -> int:
        difficulty_map = {'easy': 1, 'medium': 2, 'hard': 3}
        difficulty_value = difficulty_map.get(difficulty.lower(), 2)  # Default to medium if unknown
        
        base_points = 10 * difficulty_value
        
        time_factor = max(0, 1 - (time_taken / self.time_limit))
        time_bonus = int(5 * time_factor * difficulty_value)
        
        streak_bonus = min(self.current_streak, 5) * 2
        
        if is_correct:
            points = base_points + time_bonus + streak_bonus
        else:
            points = -base_points // 2  # Lose half the base points for incorrect answers
        
        points *= self.points_multiplier  # Apply powerup multiplier
        
        return max(-50, min(100, points))  # Ensure points are between -50 and 100

    async def award_powerups(self, accuracy: float, num_questions: int) -> int:
        powerups_earned = 0
        user_profile = await self.bot.get_user_profile(str(self.user.id))
        
        # Award powerups based on accuracy and number of questions
        if num_questions >= 20:
            if accuracy >= 90:
                powerups_earned += 3
            elif accuracy >= 80:
                powerups_earned += 2
            elif accuracy >= 70:
                powerups_earned += 1
        elif num_questions >= 10:
            if accuracy >= 90:
                powerups_earned += 2
            elif accuracy >= 80:
                powerups_earned += 1
        elif num_questions >= 5:
            if accuracy >= 90:
                powerups_earned += 1
        
        # Additional powerup for daily quiz streak
        if self.quiz_type == "daily" and user_profile.current_streak % 7 == 0 and user_profile.current_streak > 0:
            powerups_earned += 1
        
        # Distribute powerups evenly
        available_powerups = list(user_profile.powerups.keys())
        for i in range(powerups_earned):
            powerup_type = available_powerups[i % len(available_powerups)]
            user_profile.powerups[powerup_type] += 1
        
        await self.bot.save_user_profile(user_profile)
        
        return powerups_earned

    # Power-up methods
    async def streak_sponsor(self):
        self.current_streak += 1
        return "🚀 Streak Sponsor activated! Your current streak is now increased by 1."

    async def double_life(self):
        self.lives = 2
        return "❤️❤️ Double Life activated! You have two chances to answer this question."

    async def freeze_frame(self):
        self.streak_frozen = True
        return "❄️ Freeze Frame activated! Your streak won't reset if you answer incorrectly."

    async def double_points(self):
        self.points_multiplier = 2
        return "✨💥 Double Points activated! You'll earn (or lose) double points for this question."
        
api_quiz_cooldown = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.channel)

@bot.tree.command(name="quiz", description="Take a quiz")
@app_commands.describe(
    category="Category for the quiz questions",
    difficulty="Difficulty level of the questions",
    num_questions="Number of questions (1-50, default is 5)",
    time_limit="Time limit for each question (10-120 seconds, default is 30)"
)
@app_commands.choices(category=[
    app_commands.Choice(name=name.replace("_", " ").title(), value=name)
    for name in list(CATEGORY_MAP.keys()) + ["random"]
])
@app_commands.choices(difficulty=[
    app_commands.Choice(name="Easy", value="easy"),
    app_commands.Choice(name="Medium", value="medium"),
    app_commands.Choice(name="Hard", value="hard"),
    app_commands.Choice(name="Random", value="random")
])
async def quiz(
    interaction: discord.Interaction, 
    category: Optional[app_commands.Choice[str]] = None,
    difficulty: Optional[app_commands.Choice[str]] = None,
    num_questions: Optional[app_commands.Range[int, 1, 50]] = 5,
    time_limit: Optional[app_commands.Range[int, 10, 120]] = 30
):
    # Check if the interaction is in a guild
    if not interaction.guild:
        await interaction.response.send_message("Quizzes can only be started in servers, not in DMs.", ephemeral=True)
        return

    # Check for cooldown
    bucket = api_quiz_cooldown.get_bucket(interaction)
    retry_after = bucket.update_rate_limit()
    if retry_after:
        await interaction.response.send_message(
            f"Please wait {retry_after:.0f} seconds",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        # Validate and set default values
        selected_category = category.value if category else "random"
        selected_difficulty = difficulty.value if difficulty else "random"
        num_questions = num_questions if num_questions is not None else 5

        # Fetch questions from API
        api_questions = await fetch_questions(selected_category, num_questions, selected_difficulty)
        
        if not api_questions:
            await interaction.followup.send(
                "We are having issues with the catagory you selected. Try the same catagory, but dificulty at random"
            )
            return

        # Format questions
        formatted_questions = [format_question(q) for q in api_questions]

        # Create quiz view
        view = APIQuizView(bot, formatted_questions, interaction.user, quiz_type="standard", time_limit=time_limit)

        # Create instructions embed
        embed = discord.Embed(
            title="Overview", 
            description="<:TriviaIcon:1284893178297581661> Welcome to the Quiz!", 
            color=discord.Color.blue()
        )
        embed.add_field(name="Category", value=category.name if category else "Random", inline=True)
        embed.add_field(name="Difficulty", value=difficulty.name if difficulty else "Random", inline=True)
        embed.add_field(name="Time Limit", value=f"{time_limit} seconds per question", inline=True)
        embed.add_field(name="Number of Questions", value=str(num_questions), inline=True)
        embed.set_footer(text="Use /powerup for a upperhand")



        # Create start button
        start_button = discord.ui.Button(label="Start Quiz", style=discord.ButtonStyle.green)

        async def start_button_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await view.start_quiz(interaction.channel)

        start_button.callback = start_button_callback

        start_view = discord.ui.View()
        start_view.add_item(start_button)

        # Send instructions and start button
        await interaction.followup.send(embed=embed, view=start_view)

    except aiohttp.ClientError as e:
        await interaction.followup.send(f"Please try again later.")
        print(f"Quiz error (aiohttp.ClientError): {e}")
    except asyncio.TimeoutError:
        await interaction.followup.send("Please try again later.")
        print("Quiz error: API request timed out")
    except ValueError as e:
        await interaction.followup.send(f"Invalid input")
        print(f" Quiz error (ValueError): {e}")
    except Exception as e:
        await interaction.followup.send("You broke it.")
        print(f"Quiz unexpected error: {e}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="daily_quiz", description="Take the daily quiz challenge")
async def daily_quiz(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_profile = await bot.get_user_profile(user_id)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if user_profile.last_daily_quiz and user_profile.last_daily_quiz >= today:
        time_until_next = (today + timedelta(days=1)) - datetime.now()
        hours, remainder = divmod(time_until_next.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        await interaction.response.send_message(
            f"You've already taken the daily quiz today. "
            f"You can take the next daily quiz in {hours} hours and {minutes} minutes.",
            ephemeral=True
        )
        return

    await interaction.response.defer()


    try:
        # Get the daily category
        daily_category = await bot.get_daily_category()

        # Fetch 5 questions from the daily category
        api_questions = await fetch_questions(daily_category, 5, "easy")
        
        if not api_questions:
            await interaction.followup.send("We're having issues fetching questions. Please try again later.")
            return

        formatted_questions = [format_question(q) for q in api_questions]

        view = APIQuizView(bot, formatted_questions, interaction.user, quiz_type="daily")

        embed = discord.Embed(
            title="Daily Quiz Challenge",
            description="<:TriviaIcon:1284893178297581661> Welcome to today's daily quiz!",
            color=discord.Color.blue()
        )
        embed.add_field(name="Category", value=daily_category.replace("_", " ").title(), inline=True)
        embed.add_field(name="Number of Questions", value="5", inline=True)
        embed.set_footer(text="Good luck! Your streak is on the line!")

        start_button = discord.ui.Button(label="Start Daily Quiz", style=discord.ButtonStyle.green)

        async def start_button_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await view.start_quiz(interaction.channel)

        start_button.callback = start_button_callback

        start_view = discord.ui.View()
        start_view.add_item(start_button)

        await interaction.followup.send(embed=embed, view=start_view)

    except Exception as e:
        await interaction.followup.send("An error occurred. Please try again later.")
        print(f"Daily quiz error: {e}")   
        
class LeaderboardView(discord.ui.View):
    def __init__(self, bot: QuizBot, leaderboard: List[Tuple[str, int]], user_id: str, user_tier: str):
        super().__init__(timeout=60)
        self.bot = bot
        self.leaderboard = leaderboard
        self.user_id = user_id
        self.user_tier = user_tier
        self.current_page = 1
        self.total_pages = (len(leaderboard) - 1) // USERS_PER_PAGE + 1

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 1:
            self.current_page -= 1
            await self.update_leaderboard(interaction)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
            await self.update_leaderboard(interaction)

    async def update_leaderboard(self, interaction: discord.Interaction):
        embed = await self.create_leaderboard_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def create_leaderboard_embed(self) -> discord.Embed:
        start_index = (self.current_page - 1) * USERS_PER_PAGE
        end_index = start_index + USERS_PER_PAGE
        page_leaderboard = self.leaderboard[start_index:end_index]

        embed = discord.Embed(title=f"📊 Weekly {self.user_tier} Tier Leaderboard", color=discord.Color.gold())
        embed.set_thumbnail(url="https://example.com/leaderboard_icon.png")

        user_cache = {}
        async def get_username(user_id):
            if user_id not in user_cache:
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    user_cache[user_id] = user.name
                except Exception:
                    user_cache[user_id] = f"Unknown User {user_id}"
            return user_cache[user_id]

        medal_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
        leaderboard_text = ""

        for rank, (user_id, score) in enumerate(page_leaderboard, start=start_index + 1):
            username = await get_username(user_id)
            medal = medal_emojis.get(rank, "")
            leaderboard_text += f"{medal} **{rank}.** {username}: {score} points\n"

        embed.description = leaderboard_text

        user_rank = await self.bot.get_user_rank(self.user_id, self.user_tier)
        if user_rank:
            user_score = next(score for uid, score in self.leaderboard if uid == self.user_id)
            embed.add_field(name="Your Rank", value=f"#{user_rank}: {user_score} points", inline=False)

        embed.set_footer(text=f"Page {self.current_page}/{self.total_pages} | Keep quizzing to improve your rank!")
        return embed
    
@bot.tree.command(name="overall_leaderboard", description="Show the overall points leaderboard")
async def overall_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    try:
        leaderboard_data = await bot.get_overall_leaderboard()
        if not leaderboard_data:
            await interaction.followup.send("The overall leaderboard is currently empty.", ephemeral=True)
            return

        view = LeaderboardView(bot, leaderboard_data, str(interaction.user.id), "Overall")
        embed = await view.create_leaderboard_embed()
        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"Overall leaderboard error: {e}")
        await interaction.followup.send("An error occurred while fetching the leaderboard. Please try again later.", ephemeral=True)

@bot.tree.command(name="leaderboard", description="Show the weekly leaderboard for your current tier")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    try:
        user_profile = await bot.get_user_profile(str(interaction.user.id))
        user_tier = user_profile.tier

        leaderboard_data = await bot.get_tier_leaderboard(user_tier)
        if not leaderboard_data:
            await interaction.followup.send(f"The {user_tier} tier leaderboard is currently empty.", ephemeral=True)
            return

        view = LeaderboardView(bot, leaderboard_data, str(interaction.user.id), user_tier)
        embed = await view.create_leaderboard_embed()
        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"Leaderboard error: {e}")
        await interaction.followup.send("An error occurred while fetching the leaderboard. Please try again later.", ephemeral=True)
        
@bot.tree.command(name="profile", description="View a user's flashy quiz profile")
@app_commands.describe(user="The user whose profile you want to view (leave empty for your own profile)")
async def profile(interaction: discord.Interaction, user: Optional[discord.User] = None):
    await interaction.response.defer()

    # Determine the target user (the one whose profile is being viewed)
    target_user = user or interaction.user
    user_id = str(target_user.id)

    # Fetch the user's profile data (ensure these methods are async)
    user_profile = await bot.get_user_profile(user_id)
    tier_emoji, tier_color, tier_title = get_tier_details(user_profile.tier)

    # Create the embed
    embed = discord.Embed(title=f"{tier_emoji} Quiz Profile: {target_user.name}", color=tier_color)
    embed.set_thumbnail(url=target_user.display_avatar.url)

    # Add tier information
    embed.add_field(name="Tier", value=f"{tier_emoji} {user_profile.tier} - {tier_title}", inline=False)

    # Add accuracy and streak stats
    accuracy = user_profile.accuracy
    accuracy_emoji = "🎯" if accuracy > 75 else "🏹" if accuracy > 50 else "🔫"
    embed.add_field(name="Accuracy", value=f"{accuracy_emoji} {accuracy:.2f}%", inline=True)

    streak_emoji = "🔥" if user_profile.current_streak > 7 else "✨" if user_profile.current_streak > 3 else "📅"
    embed.add_field(name="Current Streak", value=f"{streak_emoji} {user_profile.current_streak} days", inline=True)
    embed.add_field(name="Longest Streak", value=f"🏆 {user_profile.longest_streak} days", inline=True)

    # Add quiz stats
    embed.add_field(name="Correct Answers", value=f"✅ {user_profile.correct_answers}", inline=True)
    embed.add_field(name="Incorrect Answers", value=f"❌ {user_profile.questions_answered - user_profile.correct_answers}", inline=True)
    embed.add_field(name="Quizzes Completed", value=f"📊 {user_profile.quizzes_completed}", inline=True)

    # Add tier rank information with progress bar
    tier_leaderboard = await bot.get_tier_leaderboard(user_profile.tier)
    user_rank = next((i for i, (uid, _) in enumerate(tier_leaderboard, start=1) if uid == user_id), None)
    
    if user_rank:
        total_users = len(tier_leaderboard)
        next_rank = user_rank - 1 if user_rank > 1 else user_rank
        progress = (total_users - user_rank + 1) / total_users
        rank_bar = create_progress_bar(progress * 100, 100, size=20)

        rank_color = discord.Color.gold() if user_rank <= 3 else discord.Color.blue()
        rank_field = f"**Rank: #{user_rank}** / {total_users}\n{rank_bar}\n"
        rank_field += f"{'🏆 Top 3!' if user_rank <= 3 else f'{next_rank} more to reach next rank!'}"

        embed.add_field(name="Tier Ranking", value=rank_field, inline=False)

        if user_rank <= 3:
            embed.color = rank_color
            embed.set_author(name="🏆 Top 3 in Tier! 🏆")
    
    # Add overall rank information with progress bar
    overall_leaderboard = await bot.get_overall_leaderboard()
    overall_rank = next((i for i, (uid, _) in enumerate(overall_leaderboard, start=1) if uid == user_id), None)
    
    if overall_rank:
        total_users = len(overall_leaderboard)
        next_rank = overall_rank - 1 if overall_rank > 1 else overall_rank
        progress = (total_users - overall_rank + 1) / total_users
        rank_bar = create_progress_bar(progress * 100, 100, size=20)

        rank_color = discord.Color.gold() if overall_rank <= 3 else discord.Color.blue()
        rank_field = f"**Overall Rank: #{overall_rank}** / {total_users}\n{rank_bar}\n"
        rank_field += f"{'🏆 Top 3 Overall!' if overall_rank <= 3 else f'{next_rank} more to reach next overall rank!'}"

        embed.add_field(name="Overall Ranking", value=rank_field, inline=False)

        if overall_rank <= 3:
            embed.color = rank_color
            embed.set_author(name="🏆 Top 3 Overall! 🏆")

    # Add motivational footer
    if user_profile.tier != "Titanium":
        next_tier = {
            "Wood": "Stone",
            "Stone": "Iron",
            "Iron": "Bronze",
            "Bronze": "Silver",
            "Silver": "Gold",
            "Gold": "Platinum",
            "Platinum": "Diamond",
            "Diamond": "Titanium",
        }
        upcoming_tier = next_tier[user_profile.tier]
        embed.set_footer(text=f"Keep quizzing to reach {upcoming_tier} tier! 💪")
    else:
        embed.set_footer(text="Incredible job reaching Titanium tier! Can you stay on top? 👑")

    # Send the response
    await interaction.followup.send(embed=embed)


# Helper function to create a text-based progress bar
def create_progress_bar(current: float, maximum: float, size: int = 10) -> str:
    if maximum == 0:  # Handle division by zero
        return '░' * size  # Return an empty progress bar if the maximum is 0
    
    filled = '█' * int(size * (current / maximum))
    empty = '░' * (size - len(filled))
    return f"{filled}{empty}"

# Helper function to get tier-specific details
def get_tier_details(tier: str) -> tuple:
    tier_details = {
        "Wood": ("🪵", discord.Color.dark_orange(), "Beginner Quizzer"),
        "Stone": ("🪨", discord.Color.light_gray(), "Novice Quizzer"),
        "Iron": ("🛠️", discord.Color.dark_gray(), "Apprentice Quizzer"),
        "Bronze": ("🥉", discord.Color.orange(), "Rising Star"),
        "Silver": ("🥈", discord.Color.light_grey(), "Quiz Veteran"),
        "Gold": ("🥇", discord.Color.gold(), "Quiz Master"),
        "Platinum": ("🏆", discord.Color.blue(), "Elite Quizzer"),
        "Diamond": ("💎", discord.Color.teal(), "Quiz Champion"),
        "Titanium": ("⚙️", discord.Color.dark_teal(), "Ultimate Quizzer")
    }

    return tier_details.get(tier, ("❓", discord.Color.default(), "Unknown"))

@bot.tree.command(name="powerup", description="Learn about available power-ups and view your inventory")
async def powerup(interaction: discord.Interaction):
    user_profile = await bot.get_user_profile(str(interaction.user.id))

    embed = discord.Embed(
        title="Power-ups",
        description="Available powerups and your current inventory:",
        color=discord.Color.orange()
    )

    powerup_descriptions = {
        "streak_sponsor": "🚀 Streak Sponsor: Increase your current streak by 1.",
        "double_life": "❤️❤️ Double Life: Get two chances to answer a question.",
        "freeze_frame": "❄️ Freeze Frame: Freeze your current streak so it won't reset on an incorrect answer.",
        "double_points": "✨💥 Double Points: Double the points for the next question, or lose double if you're wrong."
    }

    for powerup_key, description in powerup_descriptions.items():
        count = user_profile.powerups.get(powerup_key, 0)
        embed.add_field(
            name=f"{description}",
            value=f"You have: **{count}**",
            inline=False
        )

    embed.set_footer(text="Use /powerup_use during a quiz to activate a powerup!")

    await interaction.response.send_message(embed=embed, ephemeral=True)

class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message: discord.Message = None):
        super().__init__(timeout=120)  # Extend the timeout to give users more time to read
        self.bot = bot
        self.message = message  # Store the message reference for timeout handling
        self.current_page = 0

        self.pages = [
            self.general_help,
            self.powerup_help,
            self.quiz_help,
            self.leaderboard_help,
            self.profile_help,
            self.daily_quiz_help
        ]
        
        self.page_colors = [discord.Color.orange(), discord.Color.blue(), discord.Color.green(), discord.Color.gold(), discord.Color.purple(), discord.Color.red()]
    
        self.previous_button = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=True)
        self.previous_button.callback = self.previous_page
        self.add_item(self.previous_button)
        
        self.next_button = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary)
        self.next_button.callback = self.next_page
        self.add_item(self.next_button)

    async def get_embed(self, index):
        embed = await self.pages[index]()
        embed.color = self.page_colors[index]  # Dynamically assign color per page
        return embed

    async def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1

    async def previous_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        await self.update_buttons()
        await interaction.response.edit_message(embed=await self.get_embed(self.current_page), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        await self.update_buttons()
        await interaction.response.edit_message(embed=await self.get_embed(self.current_page), view=self)

    async def on_timeout(self):
        # Disable the buttons when the view times out
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # Notify users that the help session timed out
        if self.message:
            try:
                await self.message.edit(content="⏰ Help session timed out. Use `/help` to reopen.", view=self)
            except discord.NotFound:
                pass
    # Help pages
    async def general_help(self) -> discord.Embed:
        embed = discord.Embed(title="📖 Ultimate Trivia Help", color=discord.Color.blue())
        embed.description = "**Ultimate Trivia!** help:"
        embed.add_field(name="🎮 /quiz", value="Start a quiz in more than 20 topics", inline=False)
        embed.add_field(name="📅 /daily_quiz", value="Take the daily challenge and build your streak.", inline=False)
        embed.add_field(name="🏆 /leaderboard", value="View the global leaderboard and see how you rank.", inline=False)
        embed.add_field(name="👤 /profile", value="See advanced stats on any player", inline=False)
        embed.add_field(name="🚀 Powerups", value="Boost your quiz performance with powerups!", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

    async def quiz_help(self) -> discord.Embed:
        embed = discord.Embed(title="🎮 Quiz Command Help", color=discord.Color.green())
        embed.description = "Create a personalized quiz"
        embed.add_field(name="Usage", value="`/quiz [category] [difficulty] [num_questions]`", inline=False)
        embed.add_field(name="Category", value="Choose from various categories, or leave it blank for a random one.", inline=False)
        embed.add_field(name="Difficulty", value="Select from Easy, Medium, Hard, or Random.", inline=False)
        embed.add_field(name="Number of Questions", value="Choose between 1 and 50 questions (default is 5).", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

    async def leaderboard_help(self) -> discord.Embed:
        embed = discord.Embed(title="🏆 Leaderboard Command Help", color=discord.Color.gold())
        embed.description = "Take a look at some trivia masterminds"
        embed.add_field(name="Usage", value="`/leaderboard`", inline=False)
        embed.add_field(name="Features", value="• See top scorers\n• Navigate pages of the leaderboard\n• Check your rank", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

    async def profile_help(self) -> discord.Embed:
        embed = discord.Embed(title="👤 Profile Command Help", color=discord.Color.purple())
        embed.description = "Check out people's statistics"
        embed.add_field(name="Usage", value="`/profile [user]` (optional)", inline=False)
        embed.add_field(name="Features", value="• View total points\n• See questions answered\n• Accuracy and streaks", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

    async def daily_quiz_help(self) -> discord.Embed:
        embed = discord.Embed(title="📅 Daily Quiz Command Help", color=discord.Color.red())
        embed.description = "Join the daily quiz"
        embed.add_field(name="Usage", value="`/daily_quiz`", inline=False)
        embed.add_field(name="Features", value="• One quiz per day\n• Random category\n• Track your streak", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

    async def powerup_help(self) -> discord.Embed:
        embed = discord.Embed(title="🚀 Powerups Help", color=discord.Color.orange())
        embed.description = "Boost your quiz performance with powerups!"
        embed.add_field(name="Types of Powerups", value=
            "• 🚀 Streak Sponsor: Increase your current streak by 1\n"
            "• ❤️❤️ Double Life: Get two chances to answer a question\n"
            "• ❄️ Freeze Frame: Freeze your streak, preventing reset on wrong answer\n"
            "• ✨💥 Double Points: Double points for the next question (or double loss if wrong)", 
            inline=False
        )
        embed.add_field(name="How to Earn Powerups", value=
            "1. Score 80%+ on a 5+ question quiz: Earn 3 powerups\n"
            "2. Score 100% on a 5+ question quiz: Earn 5 powerups\n"
            "3. Maintain a daily streak: Earn 2 powerups every 7 days\n",
            inline=False
        )
        embed.add_field(name="Using Powerups", value=
            "During a quiz, click the 'Powerup' button to see and use your available powerups.",
            inline=False
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)} • Use the buttons below to navigate.")
        return embed

@bot.tree.command(name="help", description="Get help using Ultimate Trivia")
async def help_command(interaction: discord.Interaction):
    view = HelpView(interaction.client)  # Create the view first
    embed = await view.get_embed(0)  # Start on the Powerup Help page
    message = await interaction.response.send_message(embed=embed, view=view)
    view.message = message  # Store the message reference for timeout handling


@bot.tree.command(name="toggle_notif", description="Toggle daily quiz and powerup notifications on or off")
async def toggle_notif(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_profile = await bot.get_user_profile(user_id)

    user_profile.notifications_enabled = not user_profile.notifications_enabled
    await bot.save_user_profile(user_profile)

    status = "enabled" if user_profile.notifications_enabled else "disabled"
    await interaction.response.send_message(f"Daily quiz and powerup notifications have been {status}.", ephemeral=True)

@bot.tree.command(name="upvote", description="Get a link to upvote the bot on Top.gg")
async def upvote(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Upvote Ultimate Trivia Bot!",
        description="Support us by upvoting on Top.gg and receive 5 random powerups!",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Click the button below to upvote")

    view = UpvoteView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    # try to fit deeze nutz into yo mouth?
    try:
        synced_commands = await bot.tree.sync()
        print(f'Successfully synced {len(synced_commands)} commands.')

        # debug for commands
        for command in synced_commands:
            print(f'Command: /{command.name} - {command.description}')

    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # set trivia status 
    custom_game = discord.Game("Trivia!")
    await bot.change_presence(status=discord.Status.online, activity=custom_game)

if __name__ == "__main__":
    # Start the webhook server in a separate thread
    webhook_thread = threading.Thread(target=run_webhook_server, args=(bot,))
    webhook_thread.start()

    # Start the bot
    bot.run(DISCORD_TOKEN)
