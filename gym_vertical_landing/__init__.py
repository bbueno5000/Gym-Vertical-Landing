import gym.envs.registration as registration
import logging

logger = logging.getLogger(__name__)

registration.register(entry_point='gym_vertical_landing.envs:VerticalLandingEnv',
                      id='VerticalLanding-v0',
                      nondeterministic=True,
                      reward_threshold=1.0,
                      timestep_limit=1000)
