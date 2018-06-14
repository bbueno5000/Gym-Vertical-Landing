"""

The objective of this environment is to land a rocket on a platform.

STATE VARIABLES
---------------
The state consists of the following variables:
    - x position
    - y position
    - angle
    - first leg ground contact indicator
    - second leg ground contact indicator
    - throttle
    - engine gimbal
If vel_state is set to true, the velocities values are included:
    - x velocity
    - y velocity
    - angular velocity

all state variables are roughly in the range [-1, 1]

CONTROL INPUTS
--------------
Discrete Control Inputs:
    - gimbal left
    - gimbal right
    - throttle up
    - throttle down
    - use first control thruster
    - use second control thruster
    - no action

Continuous Control Inputs:
    - gimbal (left/right)
    - throttle (up/down)
    - control thruster (left/right)

"""
import Box2D
import gym
import gym.spaces as spaces
import gym.utils.seeding
import numpy as np


FPS = 60


class ContactDetector(Box2D.b2ContactListener):

    def __init__(self, env):
        super(ContactDetector, self).__init__()
        self.env = env

    def BeginContact(self, contact):
        if self.env.water in [contact.fixtureA.body, contact.fixtureB.body] \
        or self.env.lander in [contact.fixtureA.body, contact.fixtureB.body] \
        or self.env.containers[0] in [contact.fixtureA.body, contact.fixtureB.body] \
        or self.env.containers[1] in [contact.fixtureA.body, contact.fixtureB.body]:
            self.env.game_over = True
        else:
            for i in range(2):
                if self.env.legs[i] in [contact.fixtureA.body, contact.fixtureB.body]:
                    self.env.legs[i].ground_contact = True

    def EndContact(self, contact):
        for i in range(2):
            if self.env.legs[i] in [contact.fixtureA.body, contact.fixtureB.body]:
                self.env.legs[i].ground_contact = False


class VerticalLandingEnv(gym.Env):

    metadata = {'render.modes': ['human', 'rgb_array'],
                'video.frames_per_second': FPS}

    def __init__(self):
        self.continuous = True
        self.initial_random = 0.4    # Random scaling of initial velocity, higher is more difficult
        self.scale_s = 0.35    # Temporal Scaling, lower is faster - adjust forces appropriately
        self.start_height = 1000.0
        self.start_speed = 80.0
        self.vel_state = True    # Add velocity info to state
        # ROCKET PARAMETERS
        self.gimbal_threshold = 0.4
        self.main_engine_power = 1600 * self.scale_s
        self.min_throttle = 0.4
        self.rocket_width = 3.66 * self.scale_s
        self.rocket_height = self.rocket_width / 3.7 * 47.9
        self.engine_height = self.rocket_width * 0.5
        self.engine_width = self.engine_height * 0.7
        self.side_engine_power = 100 / FPS * self.scale_s
        self.thruster_height = self.rocket_height * 0.86
        # LEG PARAMETERS
        self.base_angle = -0.27
        self.leg_away = self.rocket_width / 2
        self.leg_length = self.rocket_width * 2.2
        self.spring_angle = 0.27
        # SHIP PARAMETERS
        self.ship_height = self.rocket_width
        self.ship_width = self.ship_height * 40
        # VIEWPORT PARAMETERS
        self.viewport_h = 720
        self.viewport_w = 500
        self.H = 1.1 * self.start_height * self.scale_s
        self.W = float(self.viewport_w) / self.viewport_h * self.H
        # SMOKE FOR VISUALS PARAMETERS
        self.max_smoke_lifetime = 2 * FPS
        self.mean = np.array([-0.034, -0.15, -0.016, 0.0024, 0.0024, 0.137, -0.02, -0.01, -0.8, 0.002])
        self.var = np.sqrt(np.array([0.08, 0.33, 0.0073, 0.0023, 0.0023, 0.8, 0.085, 0.0088, 0.063, 0.076]))
        # GENERAL PARAMETERS
        self._seed()
        self.engine = None
        self.episode_number = 0
        self.lander = None
        self.legs = []
        self.ship = None
        self.viewer = None
        self.water = None
        self.world = Box2D.b2World()
        high = np.array([1, 1, 1, 1, 1, 1, 1, np.inf, np.inf, np.inf], dtype=np.float32)
        low = -high

        if not self.vel_state:
            high = high[0:7]
            low = low[0:7]

        self.observation_space = spaces.Box(low, high, dtype=np.float32)

        if self.continuous:
            self.action_space = spaces.Box(-1.0, +1.0, (3,), dtype=np.float32)
        else:
            self.action_space = spaces.Discrete(7)

        self.reset()

    def _destroy(self):
        if not self.water:
            return

        self.world.contactListener = None
        self.world.DestroyBody(self.containers[0])
        self.world.DestroyBody(self.containers[1])
        self.world.DestroyBody(self.lander)
        self.world.DestroyBody(self.legs[0])
        self.world.DestroyBody(self.legs[1])
        self.world.DestroyBody(self.ship)
        self.world.DestroyBody(self.water)
        self.containers = []
        self.lander = None
        self.legs = []
        self.ship = None
        self.water = None

    def _seed(self, seed=None):
        self.np_random, seed = gym.utils.seeding.np_random(seed)
        return [seed]

    def render(self, mode='human', close=False):
        import gym.envs.classic_control.rendering as rendering
        if close:
            if self.viewer is not None:
                self.viewer.close()
                self.viewer = None
            return

        if self.viewer is None:
            self.viewer = rendering.Viewer(self.viewport_w, self.viewport_h)
            self.viewer.set_bounds(0, self.W, 0, self.H)
            sky = rendering.FilledPolygon(((0, 0), (0, self.H), (self.W, self.H), (self.W, 0)))
            self.sky_color = self.rgb(126, 150, 233)
            sky.set_color(*self.sky_color)
            self.sky_color_half_transparent = np.array((np.array(self.sky_color) + self.rgb(255, 255, 255))) / 2
            self.viewer.add_geom(sky)
            self.rockettrans = rendering.Transform()
            engine = rendering.FilledPolygon(((0, 0),
                                              (self.engine_width / 2, -self.engine_height),
                                              (-self.engine_width / 2, -self.engine_height)))

            self.enginetrans = rendering.Transform()
            engine.add_attr(self.enginetrans)
            engine.add_attr(self.rockettrans)
            engine.set_color(.4, .4, .4)
            self.viewer.add_geom(engine)
            self.fire = rendering.FilledPolygon(((self.engine_width * 0.4, 0),
                                                 (-self.engine_width * 0.4, 0),
                                                 (-self.engine_width * 1.2, -self.engine_height * 5),
                                                 (0, -self.engine_height * 8),
                                                 (self.engine_width * 1.2, -self.engine_height * 5)))

            self.fire.set_color(*self.rgb(255, 230, 107))
            self.firescale = rendering.Transform(scale=(1, 1))
            self.firetrans = rendering.Transform(translation=(0, -self.engine_height))
            self.fire.add_attr(self.firescale)
            self.fire.add_attr(self.firetrans)
            self.fire.add_attr(self.enginetrans)
            self.fire.add_attr(self.rockettrans)
            smoke = rendering.FilledPolygon(((self.rocket_width / 2, self.thruster_height * 1),
                                             (self.rocket_width * 3, self.thruster_height * 1.03),
                                             (self.rocket_width * 4, self.thruster_height * 1),
                                             (self.rocket_width * 3, self.thruster_height * 0.97)))

            smoke.set_color(*self.sky_color_half_transparent)
            self.smokescale = rendering.Transform(scale=(1, 1))
            smoke.add_attr(self.smokescale)
            smoke.add_attr(self.rockettrans)
            self.viewer.add_geom(smoke)
            self.gridfins = []

            for i in (-1, 1):
                finpoly = ((i * self.rocket_width * 1.1, self.thruster_height * 1.01),
                           (i * self.rocket_width * 0.4, self.thruster_height * 1.01),
                           (i * self.rocket_width * 0.4, self.thruster_height * 0.99),
                           (i * self.rocket_width * 1.1, self.thruster_height * 0.99))

                gridfin = rendering.FilledPolygon(finpoly)
                gridfin.add_attr(self.rockettrans)
                gridfin.set_color(0.25, 0.25, 0.25)
                self.gridfins.append(gridfin)

        if self.stepnumber % round(FPS / 10) == 0 and self.power > 0:
            s = [self.max_smoke_lifetime * self.power,  # total lifetime
                 0,  # current lifetime
                 self.power * (1 + 0.2 * np.random.random()),  # size
                 np.array(self.lander.position)
                 + self.power * self.rocket_width * 10 * np.array((np.sin(self.lander.angle + self.gimbal),
                                                              -np.cos(self.lander.angle + self.gimbal)))
                 + self.power * 5 * (np.random.random(2) - 0.5)]  # position
            self.smoke.append(s)

        for s in self.smoke:
            s[1] += 1
            if s[1] > s[0]:
                self.smoke.remove(s)
                continue
            t = rendering.Transform(translation=(s[3][0], s[3][1] + self.H * s[1] / 2000))
            self.viewer.draw_circle(radius=0.05 * s[1] + s[2],
                                    color=self.sky_color + (1 - (2 * s[1] / s[0] - 1) ** 2) / 3 * (self.sky_color_half_transparent - self.sky_color)).add_attr(t)

        self.viewer.add_onetime(self.fire)
        for g in self.gridfins:
            self.viewer.add_onetime(g)

        for obj in self.drawlist:
            for f in obj.fixtures:
                trans = f.body.transform
                path = [trans * v for v in f.shape.vertices]
                self.viewer.draw_polygon(path, color=obj.color1)

        for l in zip(self.legs, [-1, 1]):
            path = [self.lander.fixtures[0].body.transform * (l[1] * self.rocket_width / 2,
                    self.rocket_height / 8),
                    l[0].fixtures[0].body.transform * (l[1] * self.leg_length * 0.8, 0)]
            self.viewer.draw_polyline(path, color=self.ship.color1, linewidth=1 if self.start_height > 500 else 2)

        self.viewer.draw_polyline(((self.helipad_x2, self.terranheight + self.ship_height),
                                   (self.helipad_x1, self.terranheight + self.ship_height)),
                                    color=self.rgb(206, 206, 2),
                                    linewidth=1)

        self.rockettrans.set_translation(*self.lander.position)
        self.rockettrans.set_rotation(self.lander.angle)
        self.enginetrans.set_rotation(self.gimbal)
        self.firescale.set_scale(newx=1, newy=self.power * np.random.uniform(1, 1.3))
        self.smokescale.set_scale(newx=self.force_dir, newy=1)
        return self.viewer.render(return_rgb_array=mode == 'rgb_array')

    def rgb(self, red, green, blue):
        return float(red) / 255, float(green) / 255, float(blue) / 255

    def reset(self):
        self._destroy()
        self.world.contactListener_keepref = ContactDetector(self)
        self.world.contactListener = self.world.contactListener_keepref
        self.game_over = False
        self.gimbal = 0.0
        self.landed_ticks = 0
        self.prev_shaping = None
        self.smoke = []
        self.stepnumber = 0
        self.throttle = 0
        self.terranheight = self.H / 20
        self.shipheight = self.terranheight + self.ship_height
        # ship_pos = self.np_random.uniform(0, self.ship_width / SCALE) + self.ship_width / SCALE
        ship_pos = self.W / 2
        self.helipad_x1 = ship_pos - self.ship_width / 2
        self.helipad_x2 = self.helipad_x1 + self.ship_width
        self.helipad_y = self.terranheight + self.ship_height
        self.water = self.world.CreateStaticBody(
            fixtures=Box2D.b2FixtureDef(
                shape=Box2D.b2PolygonShape(
                    vertices=((0, 0),
                              (self.W, 0),
                              (self.W, self.terranheight),
                              (0, self.terranheight))),
                              friction=0.1,
                              restitution=0.0))

        self.water.color1 = self.rgb(70, 96, 176)
        self.ship = self.world.CreateStaticBody(
            fixtures=Box2D.b2FixtureDef(
                shape=Box2D.b2PolygonShape(
                    vertices=((self.helipad_x1, self.terranheight),
                              (self.helipad_x2, self.terranheight),
                              (self.helipad_x2, self.terranheight + self.ship_height),
                              (self.helipad_x1, self.terranheight + self.ship_height))),
                              friction=0.5,
                              restitution=0.0))

        self.containers = []
        for side in [-1, 1]:
            self.containers.append(self.world.CreateStaticBody(
                fixtures=Box2D.b2FixtureDef(
                    shape=Box2D.b2PolygonShape(
                        vertices=((ship_pos + side * 0.95 * self.ship_width / 2, self.helipad_y),
                                  (ship_pos + side * 0.95 * self.ship_width / 2, self.helipad_y + self.ship_height),
                                  (ship_pos + side * 0.95 * self.ship_width / 2 - side * self.ship_height,
                                   self.helipad_y + self.ship_height),
                                  (ship_pos + side * 0.95 * self.ship_width / 2 - side * self.ship_height, self.helipad_y))),
                                  friction=0.2,
                                  restitution=0.0)))
            self.containers[-1].color1 = self.rgb(206, 206, 2)

        self.ship.color1 = (0.2, 0.2, 0.2)
        initial_x = self.W / 2 + self.W * np.random.uniform(-0.3, 0.3)
        initial_y = self.H * 0.95
        self.lander = self.world.CreateDynamicBody(
            position=(initial_x, initial_y),
            angle=0.0,
            fixtures=Box2D.b2FixtureDef(
                shape=Box2D.b2PolygonShape(
                    vertices=((-self.rocket_width / 2, 0),
                              (self.rocket_width / 2, 0),
                              (self.rocket_width / 2, self.rocket_height),
                              (-self.rocket_width / 2, self.rocket_height))),
                              density=1.0,
                              friction=0.5,
                              categoryBits=0x0010,
                              maskBits=0x001,
                              restitution=0.0))
        self.lander.color1 = self.rgb(230, 230, 230)

        for i in [-1, +1]:
            leg = self.world.CreateDynamicBody(
                position=(initial_x - i * self.leg_away, initial_y + self.rocket_width * 0.2),
                angle=(i * self.base_angle),
                fixtures=Box2D.b2FixtureDef(
                    shape=Box2D.b2PolygonShape(
                        vertices=((0, 0),
                                  (0, self.leg_length / 25),
                                  (i * self.leg_length, 0),
                                  (i * self.leg_length, -self.leg_length / 20),
                                  (i * self.leg_length / 3, -self.leg_length / 7))),
                                  density=1,
                                  restitution=0.0,
                                  friction=0.2,
                                  categoryBits=0x0020,
                                  maskBits=0x001))

            leg.ground_contact = False
            leg.color1 = (0.25, 0.25, 0.25)
            rjd = Box2D.b2RevoluteJointDef(bodyA=self.lander,
                                           bodyB=leg,
                                           localAnchorA=(i * self.leg_away, self.rocket_width * 0.2),
                                           localAnchorB=(0, 0),
                                           enableLimit=True,
                                           maxMotorTorque=2500.0,
                                           motorSpeed=-0.05 * i,
                                           enableMotor=True)
            djd = Box2D.b2DistanceJointDef(bodyA=self.lander,
                                           bodyB=leg,
                                           anchorA=(i * self.leg_away, self.rocket_height / 8),
                                           anchorB=leg.fixtures[0].body.transform * (i * self.leg_length, 0),
                                           collideConnected=False,
                                           frequencyHz=0.01,
                                           dampingRatio=0.9)
            if i == 1:
                rjd.lowerAngle = -self.spring_angle
                rjd.upperAngle = 0
            else:
                rjd.lowerAngle = 0
                rjd.upperAngle = + self.spring_angle

            leg.joint = self.world.CreateJoint(rjd)
            leg.joint2 = self.world.CreateJoint(djd)
            self.legs.append(leg)

        self.lander.linearVelocity = (
            -self.np_random.uniform(0, self.initial_random) * \
            self.start_speed * (initial_x - self.W / 2) / self.W, -self.start_speed)

        self.lander.angularVelocity = (1 + self.initial_random) * np.random.uniform(-1, 1)
        self.drawlist = self.legs + [self.water] + [self.ship] + self.containers + [self.lander]

        if self.continuous:
            return self.step([0, 0, 0])[0]
        else:
            return self.step(6)[0]

    def step(self, action):
        self.force_dir = 0
        if self.continuous:
            np.clip(action, -1, 1)
            self.gimbal += action[0] * 0.15 / FPS
            self.throttle += action[1] * 0.5 / FPS
            if action[2] > 0.5:
                self.force_dir = 1
            elif action[2] < -0.5:
                self.force_dir = -1
        else:
            if action == 0:
                self.gimbal += 0.01
            elif action == 1:
                self.gimbal -= 0.01
            elif action == 2:
                self.throttle += 0.01
            elif action == 3:
                self.throttle -= 0.01
            elif action == 4:    # left
                self.force_dir = -1
            elif action == 5:    # right
                self.force_dir = 1

        self.gimbal = np.clip(self.gimbal, -self.gimbal_threshold, self.gimbal_threshold)
        self.throttle = np.clip(self.throttle, 0.0, 1.0)
        self.power = 0 if self.throttle == 0.0 else self.min_throttle + self.throttle * (1 - self.min_throttle)

        # main engine force
        force_pos = (self.lander.position[0], self.lander.position[1])
        force = (-np.sin(self.lander.angle + self.gimbal) * self.main_engine_power * self.power,
                  np.cos(self.lander.angle + self.gimbal) * self.main_engine_power * self.power)

        self.lander.ApplyForce(force=force, point=force_pos, wake=False)

        # control thruster force
        force_pos_c = self.lander.position + self.thruster_height * np.array((np.sin(self.lander.angle), np.cos(self.lander.angle)))
        force_c = (-self.force_dir * np.cos(self.lander.angle) * self.side_engine_power,
                    self.force_dir * np.sin(self.lander.angle) * self.side_engine_power)

        self.lander.ApplyLinearImpulse(impulse=force_c, point=force_pos_c, wake=False)
        self.world.Step(1.0 / FPS, 60, 60)
        pos = self.lander.position
        vel_l = np.array(self.lander.linearVelocity) / self.start_speed
        vel_a = self.lander.angularVelocity
        x_distance = (pos.x - self.W / 2) / self.W
        y_distance = (pos.y - self.shipheight) / (self.H - self.shipheight)
        angle = (self.lander.angle / np.pi) % 2

        if angle > 1:
            angle -= 2

        state = [2 * x_distance,
                 2 * (y_distance - 0.5),
                 angle,
                 1.0 if self.legs[0].ground_contact else 0.0,
                 1.0 if self.legs[1].ground_contact else 0.0,
                 2 * (self.throttle - 0.5),
                 (self.gimbal / self.gimbal_threshold)]

        if self.vel_state:
            state.extend([vel_l[0], vel_l[1], vel_a])

        # REWARD BEGINS -----
        # state variables for reward
        distance = np.linalg.norm((3 * x_distance, y_distance))    # weight x position more
        speed = np.linalg.norm(vel_l)
        groundcontact = self.legs[0].ground_contact or self.legs[1].ground_contact
        brokenleg = (self.legs[0].joint.angle < 0 or self.legs[1].joint.angle > -0) and groundcontact
        outside = abs(pos.x - self.W / 2) > self.W / 2 or pos.y > self.H
        fuelcost = 0.1 * (0 * self.power + abs(self.force_dir)) / FPS
        landed = self.legs[0].ground_contact and self.legs[1].ground_contact and speed < 0.1
        done = False
        reward = -fuelcost

        if outside or brokenleg:
            self.game_over = True

        if self.game_over:
            done = True
        else:
            # reward shaping
            shaping = -0.5 * (distance + speed + abs(angle) ** 2)
            shaping += 0.1 * (self.legs[0].ground_contact + self.legs[1].ground_contact)
            if self.prev_shaping is not None:
                reward += shaping - self.prev_shaping
            self.prev_shaping = shaping
            if landed:
                self.landed_ticks += 1
            else:
                self.landed_ticks = 0
            if self.landed_ticks == FPS:
                reward = 1.0
                done = True

        if done:
            reward += max(-1, 0 - 2 * (speed + distance + abs(angle) + abs(vel_a)))
        elif not groundcontact:
            reward -= 0.25 / FPS

        reward = np.clip(reward, -1, 1)
        # REWARD ENDS -----

        self.stepnumber += 1
        state = (state - self.mean[:len(state)]) / self.var[:len(state)]
        return np.array(state), reward, done, {}
