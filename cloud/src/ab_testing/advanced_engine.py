"""AutoReels Pro v10 — Advanced A/B Testing Engine"""

from dataclasses import dataclass
from typing import Dict, Tuple, List
from scipy.stats import norm, binomtest as binom_test, chi2_contingency
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

@dataclass
class TestVariant:
    """One A/B test variant"""
    name: str  # 'variant_a', 'variant_b', 'variant_c'
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    cumulative_views: int = 0
    avg_engagement_duration: float = 0.0
    last_updated: datetime = None

class AdvancedABTestEngine:
    """
    Bayesian A/B Testing for real statistical rigor.
    - Tests: thumbnails, captions, posting times, angles
    - Metrics: CTR, conversion rate, engagement duration
    - Significance: p < 0.05 required before declaring winner
    - Confidence intervals: 95% CI for all estimates
    """
    
    def __init__(self, db_session):
        self.db = db_session
        self.tests: Dict[str, Dict[str, TestVariant]] = {}
    
    def start_test(self, test_id: str, variants: List[str], metric: str = 'ctr'):
        """Start a new A/B test"""
        self.tests[test_id] = {
            variant: TestVariant(name=variant)
            for variant in variants
        }
        logger.info(f"Started test '{test_id}' with variants: {variants}")
    
    def record_impression(self, test_id: str, variant: str):
        """Record an impression for a variant"""
        if test_id in self.tests and variant in self.tests[test_id]:
            self.tests[test_id][variant].impressions += 1
    
    def record_click(self, test_id: str, variant: str):
        """Record a click/engagement"""
        if test_id in self.tests and variant in self.tests[test_id]:
            variant_obj = self.tests[test_id][variant]
            variant_obj.clicks += 1
            variant_obj.last_updated = datetime.utcnow()
    
    def get_ctr(self, variant_obj: TestVariant) -> float:
        """Calculate CTR for variant"""
        if variant_obj.impressions == 0:
            return 0.0
        return variant_obj.clicks / variant_obj.impressions
    
    def get_confidence_interval(self, variant_obj: TestVariant, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Get 95% confidence interval for CTR using Wilson score interval.
        More accurate than normal approximation for binary proportions.
        """
        n = variant_obj.impressions
        x = variant_obj.clicks
        
        if n == 0:
            return (0.0, 0.0)
        
        p = x / n
        z = norm.ppf((1 + confidence) / 2)
        
        denominator = 1 + z**2 / n
        center = (p + z**2 / (2*n)) / denominator
        adjusted_margin = z * np.sqrt((p * (1 - p) / n) + (z**2 / (4 * n**2))) / denominator
        
        lower = max(0, center - adjusted_margin)
        upper = min(1, center + adjusted_margin)
        
        return (lower, upper)
    
    def bayesian_update(self, variant_a: TestVariant, variant_b: TestVariant) -> dict:
        """
        Bayesian update: calculate probability that variant_b is better than variant_a.
        Uses Beta distribution posterior.
        """
        # Beta priors (weak: uniform)
        alpha_a = 1 + variant_a.clicks
        beta_a = 1 + (variant_a.impressions - variant_a.clicks)
        
        alpha_b = 1 + variant_b.clicks
        beta_b = 1 + (variant_b.impressions - variant_b.clicks)
        
        # Monte Carlo: sample from posteriors and count how often B > A
        samples_per_posterior = 100000
        theta_a = np.random.beta(alpha_a, beta_a, samples_per_posterior)
        theta_b = np.random.beta(alpha_b, beta_b, samples_per_posterior)
        
        # Probability that B is better
        prob_b_better = np.mean(theta_b > theta_a)
        
        # Expected loss (BvA): how much CTR we lose if we choose A when B is better
        expected_loss = np.mean(np.maximum(0, theta_b - theta_a))
        
        return {
            'prob_b_better': prob_b_better,
            'expected_loss_if_choose_a': expected_loss,
            'expected_win_if_choose_b': np.mean(np.maximum(0, theta_b - theta_a)) if prob_b_better > 0.5 else 0
        }
    
    def statistical_test(self, test_id: str) -> dict:
        """
        Perform statistical significance test (Chi-squared).
        Returns: winner, p_value, effect_size, recommendation
        """
        if test_id not in self.tests:
            return {'error': 'Test not found'}
        
        variants = self.tests[test_id]
        if len(variants) < 2:
            return {'error': 'Need at least 2 variants'}
        
        # Check minimum sample size (30 minimum per variant)
        min_samples = min(v.impressions for v in variants.values())
        if min_samples < 30:
            return {
                'status': 'insufficient_data',
                'min_samples_needed': 30,
                'current_samples': min_samples,
                'percent_complete': f"{(min_samples / 30) * 100:.0f}%"
            }
        
        # Chi-squared test
        contingency_table = [
            [v.clicks, v.impressions - v.clicks]
            for v in variants.values()
        ]
        chi2, p_value, dof, expected = chi2_contingency(contingency_table)
        
        # Calculate effect size (Cramer's V)
        n = sum(sum(row) for row in contingency_table)
        cramers_v = np.sqrt(chi2 / (n * (min(len(contingency_table), 2) - 1)))
        
        # Find winner
        variant_list = list(variants.values())
        ctrs = [self.get_ctr(v) for v in variant_list]
        winner_idx = np.argmax(ctrs)
        winner = list(variants.keys())[winner_idx]
        
        # Recommendation
        is_significant = p_value < 0.05
        recommendation = (
            f"✅ {winner.upper()} is statistically significant winner (p={p_value:.4f}, CTR={ctrs[winner_idx]:.1%})"
            if is_significant
            else f"⚠️ No significant difference yet. Continue testing. Leader: {winner} ({ctrs[winner_idx]:.1%})"
        )
        
        return {
            'status': 'complete' if is_significant else 'ongoing',
            'winner': winner if is_significant else None,
            'p_value': p_value,
            'effect_size': cramers_v,
            'is_significant': is_significant,
            'results': {
                variant: {
                    'ctr': self.get_ctr(v),
                    'ci': self.get_confidence_interval(v),
                    'impressions': v.impressions,
                    'clicks': v.clicks
                }
                for variant, v in variants.items()
            },
            'recommendation': recommendation
        }
    
    def get_winner_ucb(self, test_id: str) -> Tuple[str, float]:
        """
        Upper Confidence Bound (UCB) for best arm selection.
        Exploration-exploitation tradeoff.
        """
        if test_id not in self.tests:
            return None, None
        
        variants = self.tests[test_id]
        ucb_scores = {}
        
        for name, variant in variants.items():
            ctr = self.get_ctr(variant)
            # UCB1 formula: mean + sqrt(ln(N) / n)
            exploration_bonus = np.sqrt(np.log(sum(v.impressions for v in variants.values())) / max(variant.impressions, 1))
            ucb = ctr + exploration_bonus
            ucb_scores[name] = ucb
        
        winner = max(ucb_scores, key=ucb_scores.get)
        return winner, ucb_scores[winner]
    
    def power_analysis(self, baseline_ctr: float, min_detectable_effect: float = 0.1) -> dict:
        """
        Calculate required sample size to detect effect with 80% power.
        """
        from scipy.stats import norm
        
        # Effect size (Cohen's h for proportions)
        h = 2 * (np.arcsin(np.sqrt(baseline_ctr + min_detectable_effect)) - np.arcsin(np.sqrt(baseline_ctr)))
        
        # Required sample size per group (80% power, 5% significance)
        z_alpha = norm.ppf(0.975)  # 2-tailed, 0.05
        z_beta = norm.ppf(0.80)
        
        n_per_group = ((z_alpha + z_beta) / h) ** 2
        
        return {
            'baseline_ctr': baseline_ctr,
            'min_detectable_effect': min_detectable_effect,
            'target_ctr': baseline_ctr * (1 + min_detectable_effect),
            'sample_size_per_group': int(np.ceil(n_per_group)),
            'total_sample_size': int(np.ceil(n_per_group * 2))
        }
    
    def recommend_allocation(self, test_id: str) -> dict:
        """
        Thompson Sampling allocation: assign traffic proportionally to good performers.
        """
        if test_id not in self.tests:
            return {'error': 'Test not found'}
        
        variants = self.tests[test_id]
        
        # Sample from Beta posteriors
        posterior_samples = {}
        for name, variant in variants.items():
            alpha = 1 + variant.clicks
            beta = 1 + (variant.impressions - variant.clicks)
            posterior_samples[name] = np.random.beta(alpha, beta, 10000)
        
        # Calculate allocation as fraction of traffic
        mean_rates = {name: np.mean(samples) for name, samples in posterior_samples.items()}
        total = sum(mean_rates.values())
        
        allocation = {
            name: mean_rates[name] / total
            for name in mean_rates
        }
        
        return {
            'allocation': allocation,
            'recommendation': f"Allocate traffic: {', '.join(f'{k}: {v:.0%}' for k, v in allocation.items())}"
        }

# Example usage in tasks.py:
"""
@app.task
def evaluate_ab_test(test_id: str):
    from src.ab_testing.advanced_engine import AdvancedABTestEngine
    engine = AdvancedABTestEngine(db)
    results = engine.statistical_test(test_id)
    if results.get('is_significant'):
        winner = results['winner']
        logger.info(f"Test {test_id} complete! Winner: {winner}")
        # Auto-allocate 100% traffic to winner
    else:
        # Recommend Thompson allocation
        allocation = engine.recommend_allocation(test_id)
        logger.info(f"Current allocation: {allocation}")
"""
