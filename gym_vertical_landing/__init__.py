import gym.envs.registration as registration
import logging

logger = logging.getLogger(__name__)

registration.register(id='VerticalLanding-v0',
                      entry_point='gym_vertical_landing.envs:VerticalLandingEnv',
                      timestep_limit=1000,
                      reward_threshold=1.0,
                      nondeterministic = True)
