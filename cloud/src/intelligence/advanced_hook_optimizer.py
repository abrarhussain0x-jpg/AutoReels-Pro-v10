"""AutoReels Pro v10 — Advanced Hook Optimizer (Contextual Bandit)"""

import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
from scipy.stats import beta

logger = logging.getLogger(__name__)

@dataclass
class HookArm:
    """One hook phrase variant with performance history"""
    phrase: str
    niche: str
    platform: str
    angle: str
    successes: int = 0  # Clicks/engagement
    failures: int = 0   # No engagement
    impressions: int = 0
    cumulative_views_3s: int = 0  # 3-second retention metric
    alpha: float = 1.0  # Beta distribution parameters
    beta_param: float = 1.0
    last_updated: datetime = None

class AdvancedHookOptimizer:
    """
    Thompson Sampling + Contextual Bandits for hook phrase learning.
    - Learns which exact hook phrases drive retention PER platform × niche × angle
    - Uses Beta distribution (not just UCB1) for exploration-exploitation tradeoff
    - Contextual: adjusts for time-of-day, trending topics, audience mood
    - Remembers: "how did THIS hook perform with THIS niche on THIS platform?"
    """
    
    def __init__(self, db_session):
        self.db = db_session
        self.arms: Dict[str, List[HookArm]] = {}
        self.context_history = []
        self.load_from_db()
    
    def load_from_db(self):
        """Load historical hooks from database"""
        from src.database.schema import Hook
        hooks = self.db.query(Hook).all()
        
        for hook in hooks:
            key = f"{hook.niche}:{hook.platform}:{hook.angle}"
            if key not in self.arms:
                self.arms[key] = []
            
            arm = HookArm(
                phrase=hook.phrase,
                niche=hook.niche,
                platform=hook.platform,
                angle=hook.angle,
                successes=hook.clicks or 0,
                failures=hook.impressions - hook.clicks if hook.impressions else 0,
                impressions=hook.impressions or 0,
                cumulative_views_3s=int(hook.retention_3s * 1000),  # Approximate
                last_updated=hook.created_at
            )
            # Calculate Beta distribution parameters
            arm.alpha = 1 + arm.successes
            arm.beta_param = 1 + arm.failures
            self.arms[key].append(arm)
        
        logger.info(f"Loaded {sum(len(v) for v in self.arms.values())} hook arms from database")
    
    def select_hook(self, context: dict) -> Tuple[str, str]:
        """
        Select best hook for a specific context using Thompson Sampling.
        Context: {niche, platform, angle, hour_of_day, trending_topic, audience}
        Returns: (hook_phrase, arm_key)
        """
        niche = context.get('niche', 'general')
        platform = context.get('platform', 'facebook')
        angle = context.get('angle', 'education')
        
        key = f"{niche}:{platform}:{angle}"
        
        if key not in self.arms or not self.arms[key]:
            logger.warning(f"No hooks found for {key}; using seed phrase")
            return self._get_seed_hook(angle), key
        
        arms = self.arms[key]
        
        # Thompson Sampling: sample from Beta posterior for each arm
        samples = []
        for arm in arms:
            # Sample from Beta(alpha, beta) — success rate
            theta = np.random.beta(arm.alpha, arm.beta_param)
            
            # Apply context adjustments
            theta *= self._context_boost(context, arm)
            
            samples.append((theta, arm))
        
        # Select arm with highest sample
        selected_theta, selected_arm = max(samples, key=lambda x: x[0])
        
        logger.info(
            f"Selected hook '{selected_arm.phrase}' for {niche}/{platform}/{angle} "
            f"(Thompson sample: {selected_theta:.3f}, successes: {selected_arm.successes})"
        )
        
        return selected_arm.phrase, key
    
    def _context_boost(self, context: dict, arm: HookArm) -> float:
        """
        Boost hook selection based on contextual factors.
        - Time of day: some hooks work better at peak hours
        - Trending topics: "viral" hooks get boost if topic is trending
        - Audience sentiment: positive hooks if positive sentiment detected
        - Platform momentum: hooks that worked on this platform recently
        """
        boost = 1.0
        
        # Time boost
        hour = context.get('hour', 12)
        peak_hours = [9, 12, 18, 21]
        if hour in peak_hours:
            boost *= 1.2
        
        # Trending topic boost
        if context.get('is_trending'):
            boost *= 1.3
        
        # Sentiment boost
        sentiment = context.get('sentiment', 'neutral')
        if sentiment == 'positive' and arm.phrase in ['amazing', 'viral', 'incredible']:
            boost *= 1.15
        
        # Recency boost (recent = more relevant)
        if arm.last_updated:
            days_old = (datetime.utcnow() - arm.last_updated).days
            recency = max(0.8, 1.0 - (days_old / 30))
            boost *= recency
        
        return boost
    
    def _get_seed_hooks(self, angle: str) -> List[str]:
        """Base hook phrases per angle (from v10 README)"""
        seeds = {
            'education': [
                "This one trick teaches you...",
                "5-minute lesson nobody talks about",
                "The simple explanation that changed my mind",
                "Neuroscientists hate this one simple trick",
                "POV: You're learning this for the first time",
                "Most people don't know this about...",
            ],
            'entertainment': [
                "POV: You witness this unhinged moment",
                "This is what nobody expected",
                "Literally not prepared for this",
                "The crossover nobody asked for",
                "Chaos mode activated",
                "Wait for the second half",
            ],
            'lifestyle': [
                "Habit that changed my day",
                "Why everyone should try this",
                "This routine costs $0",
                "The 5-minute reset",
                "Your future self will thank you",
                "Literally everyone needs this",
            ],
            'gaming': [
                "Speedrunning this broke the game",
                "The exploit they don't want you to know",
                "1v5 clutch moment",
                "Casuals vs. pros: the difference",
                "This build is INSANE",
                "The meta nobody uses",
            ],
            'anime': [
                "That moment changed everything",
                "Nobody saw this coming",
                "The power-up was crazy",
                "POV: You missed this anime",
                "This plot twist rewired me",
                "The animation quality was insane",
            ]
        }
        return seeds.get(angle, seeds['education'])
    
    def _get_seed_hook(self, angle: str) -> str:
        """Get a random seed hook for initialization"""
        seeds = self._get_seed_hooks(angle)
        import random
        return random.choice(seeds)
    
    def record_performance(self, hook_phrase: str, context: dict, metrics: dict):
        """
        Record actual performance of a hook.
        metrics: {clicks, impressions, retention_3s_rate, velocity}
        """
        niche = context.get('niche', 'general')
        platform = context.get('platform', 'facebook')
        angle = context.get('angle', 'education')
        
        key = f"{niche}:{platform}:{angle}"
        
        if key not in self.arms:
            self.arms[key] = []
        
        # Find or create arm
        arm = None
        for a in self.arms[key]:
            if a.phrase == hook_phrase:
                arm = a
                break
        
        if not arm:
            arm = HookArm(
                phrase=hook_phrase,
                niche=niche,
                platform=platform,
                angle=angle
            )
            self.arms[key].append(arm)
        
        # Update performance
        clicks = metrics.get('clicks', 0)
        impressions = metrics.get('impressions', 1)
        retention_3s = metrics.get('retention_3s_rate', 0)
        
        arm.successes += clicks
        arm.failures += (impressions - clicks)
        arm.impressions += impressions
        arm.cumulative_views_3s += int(retention_3s * 1000)
        arm.last_updated = datetime.utcnow()
        
        # Update Beta parameters
        arm.alpha = 1 + arm.successes
        arm.beta_param = 1 + arm.failures
        
        # Calculate expected CTR
        expected_ctr = arm.successes / max(arm.impressions, 1)
        
        logger.info(
            f"Updated hook '{hook_phrase}' for {key}: "
            f"CTR={expected_ctr:.1%}, impressions={arm.impressions}, "
            f"retention_3s={arm.cumulative_views_3s / max(arm.impressions, 1):.1%}"
        )
        
        # Save to DB
        self._save_to_db(arm)
    
    def _save_to_db(self, arm: HookArm):
        """Persist hook performance to database"""
        from src.database.schema import Hook
        existing = self.db.query(Hook).filter(
            Hook.phrase == arm.phrase,
            Hook.niche == arm.niche,
            Hook.platform == arm.platform,
            Hook.angle == arm.angle
        ).first()
        
        if existing:
            existing.clicks = arm.successes
            existing.impressions = arm.impressions
            existing.engagement_rate = arm.successes / max(arm.impressions, 1)
            existing.retention_3s = arm.cumulative_views_3s / max(arm.impressions, 1)
            existing.ucb1_weight = arm.alpha / (arm.alpha + arm.beta_param)
        else:
            hook = Hook(
                niche=arm.niche,
                platform=arm.platform,
                angle=arm.angle,
                phrase=arm.phrase,
                clicks=arm.successes,
                impressions=arm.impressions,
                engagement_rate=arm.successes / max(arm.impressions, 1),
                retention_3s=arm.cumulative_views_3s / max(arm.impressions, 1)
            )
            self.db.add(hook)
        
        self.db.commit()
    
    def get_leaderboard(self, niche: str, platform: str, angle: str, top_n: int = 10) -> List[dict]:
        """Get top-performing hooks for a niche/platform/angle"""
        key = f"{niche}:{platform}:{angle}"
        
        if key not in self.arms:
            return []
        
        # Sort by success rate (CTR)
        ranked = sorted(
            self.arms[key],
            key=lambda a: (a.successes / max(a.impressions, 1), a.impressions),
            reverse=True
        )[:top_n]
        
        return [
            {
                'phrase': a.phrase,
                'ctr': a.successes / max(a.impressions, 1),
                'impressions': a.impressions,
                'retention_3s': a.cumulative_views_3s / max(a.impressions, 1),
                'thompson_score': np.random.beta(a.alpha, a.beta_param),
                'confidence': a.impressions / 100  # Confidence in estimate
            }
            for a in ranked
        ]
    
    def get_all_stats(self) -> dict:
        """Get aggregate statistics across all hooks"""
        total_arms = sum(len(v) for v in self.arms.values())
        total_impressions = sum(
            arm.impressions
            for arms in self.arms.values()
            for arm in arms
        )
        total_engagement = sum(
            arm.successes
            for arms in self.arms.values()
            for arm in arms
        )
        
        return {
            'total_arms': total_arms,
            'total_impressions': total_impressions,
            'total_engagement': total_engagement,
            'overall_engagement_rate': total_engagement / max(total_impressions, 1),
            'contexts_tracked': len(self.arms)
        }
